from __future__ import annotations

import hashlib
import json
import re
import subprocess
import time
import zipfile
from pathlib import Path

from fastapi.testclient import TestClient

import admin_api
from admin_api import create_admin_app
from navigation_terrain_projection_store import (
    NavigationTerrainProjectionResolution,
    compile_navigation_terrain_projection,
)


ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "docs" / "admin" / "scout-dashboard-v0.1.html"
DOC = ROOT / "docs" / "admin" / "scout-dashboard-v0.1.md"
PRETRIP_PAGE = ROOT / "docs" / "admin" / "phase4-pretrip-planning.html"
AFTER_ACTION_PAGE = ROOT / "docs" / "admin" / "phase1-after-action.html"
DEBUG_PAGE = ROOT / "docs" / "admin" / "phase-3-5-runtime-debug.html"
LAYER_CONTRACT_DOC = ROOT / "docs" / "specs" / "scout-admin-map-layer-contract.md"
WEATHER_DOC = ROOT / "docs" / "specs" / "scout-weather-environment-sensing.md"
SMOKE_TOOL = ROOT / "tools" / "admin_ui_visual_smoke.js"


def test_scout_dashboard_page_serves_static_shell() -> None:
    client = TestClient(create_admin_app())

    response = client.get("/admin/dashboard")

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert "Scout Dashboard v0.1" in response.text
    assert 'id="dashboardShell"' in response.text
    assert 'id="dashboardMap"' in response.text
    assert 'id="dashboardAgent"' in response.text
    assert 'id="dashboardEvidence"' in response.text


def test_navigation_terrain_intelligence_api_projects_bounded_workspace_evidence(
    tmp_path: Path,
) -> None:
    project_id = "navigation-terrain-demo"
    project_root = tmp_path / project_id
    terrain_ref = "outputs/layers/normalized/terrain_visualization.geojson"
    samples_ref = "outputs/layers/normalized/terrain_route_samples.geojson"
    risk_ref = "outputs/layers/candidates/terrain_risk_candidates.json"
    (project_root / "project.json").parent.mkdir(parents=True, exist_ok=True)
    (project_root / "project.json").write_text(
        json.dumps(
                {
                    "project_id": project_id,
                    "imagery_source_route_bbox_wgs84": {
                        "west": 121.1,
                        "south": 24.0,
                        "east": 121.2,
                        "north": 24.1,
                    },
                    "route": {
                        "bounds": {
                            "max_lat": 25.1,
                            "max_lon": 122.2,
                            "min_lat": 25.0,
                            "min_lon": 122.1,
                        }
                    },
                "terrain_visualization_ref": terrain_ref,
                "terrain_route_samples_ref": samples_ref,
                "terrain_risk_candidates_ref": risk_ref,
            }
        ),
        encoding="utf-8",
    )
    terrain_path = project_root / terrain_ref
    terrain_path.parent.mkdir(parents=True, exist_ok=True)
    terrain_path.write_text(
        json.dumps(
            {
                "counts": {
                    "source_dtm_tile_count": 1,
                    "contour_marker_count": 12,
                    "slope_class_counts": {"slope-30-40": 9},
                },
                "dtm_grid": {
                    "bbox_wgs84": {
                        "west": 121.1,
                        "south": 24.0,
                        "east": 121.2,
                        "north": 24.1,
                    },
                    "crs": "EPSG:3826-compatible",
                    "cell_resolution_m": 20,
                    "selected_cell_count": 30,
                },
                "features": [],
                "raster_overlays": [
                    {
                        "mode": "contours",
                        "source_path": (
                            "outputs/layers/normalized/terrain_contours.png"
                        ),
                        "bbox_wgs84": {
                            "west": 121.1,
                            "south": 24.0,
                            "east": 121.2,
                            "north": 24.1,
                        },
                        "pixel_width": 432,
                        "pixel_height": 169,
                        "cell_resolution_m": 20,
                        "sha256": "a" * 64,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    sample_path = project_root / samples_ref
    sample_path.parent.mkdir(parents=True, exist_ok=True)
    sample_path.write_text(
        json.dumps(
            {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "geometry": {
                            "type": "Point",
                            "coordinates": [121.15, 24.05],
                        },
                        "properties": {
                            "candidate_id": "sample-1",
                            "distance_m": 0,
                            "elevation_m": 2200,
                            "pretrip_risk": 60,
                            "teii_20m": 72,
                            "tri": 80,
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    risk_path = project_root / risk_ref
    risk_path.parent.mkdir(parents=True, exist_ok=True)
    risk_path.write_text(
        json.dumps(
            {
                "candidates": [
                    {
                        "candidate_id": "risk-1",
                        "candidate_kind": "terrain_risk_candidate",
                        "lon": 121.16,
                        "lat": 24.06,
                        "reason": "candidate review",
                        "risk_dimensions": {"teii_20m": 91},
                        "source_refs": ["outputs/risk/source.json#risk-1"],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    compile_navigation_terrain_projection(
        project_root,
        project=json.loads((project_root / "project.json").read_text()),
        project_id=project_id,
        compiled_at="2026-07-29T07:00:00Z",
    )
    client = TestClient(create_admin_app(pretrip_workspace_root=tmp_path))

    response = client.get(
        f"/admin/pretrip/projects/{project_id}/navigation-terrain-intelligence"
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["status"] == "ready_with_structure_gaps"
    assert payload["terrain_surface"]["available_overlay_modes"] == ["contours"]
    assert payload["route_samples"]["rendered_count"] == 1
    assert payload["risk_candidates"]["rendered_count"] == 1
    assert payload["feature_extraction"]["ridge"]["status"] == "not_prepared"
    assert payload["terrain_structures"]["status"] == "not_prepared"
    assert payload["source_ledger"]["boundary"]["raw_gpx_embedded"] is False
    assert payload["route_topology"]["status"] == "not_prepared"
    assert payload["boundary"]["candidate_only"] is True
    assert payload["boundary"]["runtime_safety_truth"] is False
    assert payload["boundary"]["safe_or_walkable"] == "not_determined"
    assert payload["terrain_raster_dem"]["status"] == "not_prepared"
    assert payload["terrain_raster_dem"]["preparation_required"] is True
    assert payload["terrain_raster_dem"]["boundary"]["runtime_safety_truth"] is False
    assert payload["orientation_basemap"] == {
        "status": "ready",
        "source_id": "happyman_rudy_twmap",
        "cache_layer_id": "imagery",
        "bounds_wgs84": {
            "west": 121.1,
            "south": 24.0,
            "east": 121.2,
            "north": 24.1,
        },
        "boundary": {
            "candidate_only": True,
            "runtime_safety_truth": False,
            "terrain_evidence": False,
            "workspace_file_mutation_allowed": False,
        },
    }


def test_navigation_terrain_dem_manifest_and_tile_are_read_only_allowlisted(
    tmp_path: Path,
) -> None:
    project_id = "navigation-terrain-dem-demo"
    project_root = tmp_path / project_id
    manifest_ref = "outputs/navigation/terrain_rgb/manifest.json"
    tile_ref = "outputs/navigation/terrain_rgb/version/tiles/13/6854/3532.png"
    tile_body = bytes.fromhex(
        "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
        "0000000d49444154789c6360606060000000050001a5f645400000000049454e44"
        "ae426082"
    )
    tile_sha256 = hashlib.sha256(tile_body).hexdigest()
    tile_path = project_root / tile_ref
    tile_path.parent.mkdir(parents=True)
    tile_path.write_bytes(tile_body)
    manifest_path = project_root / manifest_ref
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        json.dumps(
            {
                "schema_version": "scout_navigation_terrain_dem.v1",
                "artifact_kind": "navigation_terrain_raster_dem_tiles",
                "project_id": project_id,
                "status": "ready",
                "prepared_at": "2026-08-07T07:00:00Z",
                "encoding": "mapbox",
                "resampling": "nearest",
                "tile_size": 256,
                "minzoom": 13,
                "maxzoom": 13,
                "tile_count": 1,
                "tile_block": {
                    "x_min": 6854,
                    "x_max": 6854,
                    "y_min": 3532,
                    "y_max": 3532,
                },
                "bounds_wgs84": {
                    "west": 121.201171875,
                    "south": 24.006326198751132,
                    "east": 121.2451171875,
                    "north": 24.04646399966659,
                },
                "source_cell_resolution_m": 20,
                "source_supported_cell_count": 65536,
                "source_fingerprint": "a" * 64,
                "coverage_strategy": "largest_complete_slippy_tile_block",
                "nodata_policy": "exclude_incomplete_tiles",
                "alpha_nodata_supported": False,
                "tile_url_template": (
                    f"/admin/pretrip/projects/{project_id}/terrain-dem/"
                    "{z}/{x}/{y}.png"
                ),
                "tiles": [
                    {
                        "z": 13,
                        "x": 6854,
                        "y": 3532,
                        "source_ref": tile_ref,
                        "sha256": tile_sha256,
                    }
                ],
                "limitations": ["candidate-only visualization"],
                "boundary": {
                    "candidate_only": True,
                    "human_review_required": True,
                    "runtime_safety_truth": False,
                    "safe_or_walkable": "not_determined",
                    "unsupported_cells_encoded_as_terrain": False,
                },
            }
        ),
        encoding="utf-8",
    )
    (project_root / "project.json").write_text(
        json.dumps(
            {
                "project_id": project_id,
                "navigation_terrain_dem_manifest_ref": manifest_ref,
            }
        ),
        encoding="utf-8",
    )
    client = TestClient(create_admin_app(pretrip_workspace_root=tmp_path))

    manifest_response = client.get(
        f"/admin/pretrip/projects/{project_id}/terrain-dem/manifest"
    )
    tile_response = client.get(
        f"/admin/pretrip/projects/{project_id}/terrain-dem/13/6854/3532.png"
    )
    missing_response = client.get(
        f"/admin/pretrip/projects/{project_id}/terrain-dem/13/6855/3532.png"
    )

    assert manifest_response.status_code == 200
    assert manifest_response.json()["status"] == "ready"
    assert manifest_response.json()["tile_count"] == 1
    assert manifest_response.json()["resampling"] == "nearest"
    assert manifest_response.json()["boundary"]["candidate_only"] is True
    assert manifest_response.json()["boundary"]["workspace_file_mutation_allowed"] is False
    assert tile_response.status_code == 200
    assert tile_response.content == tile_body
    assert tile_response.headers["x-scout-terrain-dem-hash"] == tile_sha256
    assert tile_response.headers["x-scout-runtime-safety-truth"] == "false"
    assert missing_response.status_code == 404


def test_navigation_terrain_intelligence_api_returns_read_only_status_without_blocking(
    tmp_path: Path,
    monkeypatch,
) -> None:
    project_id = "navigation-terrain-preparing"
    project_root = tmp_path / project_id
    project_root.mkdir()
    (project_root / "project.json").write_text(
        json.dumps({"project_id": project_id}),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        admin_api,
        "inspect_navigation_terrain_projection",
        lambda *_args, **_kwargs: NavigationTerrainProjectionResolution(
            http_status=200,
            payload={
                "schema_version": "scout_navigation_terrain_intelligence.v0",
                "artifact_kind": "navigation_terrain_intelligence_projection_status",
                "project_id": project_id,
                "status": "not_prepared",
                "projection_state": "not_prepared",
                "preparation_required": True,
                "retry_after_ms": None,
                "boundary": {
                    "candidate_only": True,
                    "runtime_safety_truth": False,
                    "workspace_file_mutation_allowed": False,
                },
            },
        ),
    )
    client = TestClient(create_admin_app(pretrip_workspace_root=tmp_path))

    response = client.get(
        f"/admin/pretrip/projects/{project_id}/navigation-terrain-intelligence"
    )

    assert response.status_code == 200
    assert response.json()["status"] == "not_prepared"
    assert response.json()["preparation_required"] is True
    assert response.json()["retry_after_ms"] is None


def test_navigation_terrain_intelligence_get_does_not_prepare_or_write(
    tmp_path: Path,
    monkeypatch,
) -> None:
    project_id = "navigation-terrain-read-only"
    project_root = tmp_path / project_id
    project_root.mkdir()
    project_path = project_root / "project.json"
    project_path.write_text(
        json.dumps({"project_id": project_id}),
        encoding="utf-8",
    )
    original_project = project_path.read_bytes()

    def reject_write_resolver(*_args, **_kwargs):
        raise AssertionError("GET must not start Navigation projection preparation")

    monkeypatch.setattr(
        "navigation_terrain_projection_store.resolve_navigation_terrain_projection",
        reject_write_resolver,
    )
    client = TestClient(create_admin_app(pretrip_workspace_root=tmp_path))

    response = client.get(
        f"/admin/pretrip/projects/{project_id}/navigation-terrain-intelligence"
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["status"] == "not_prepared"
    assert payload["projection_state"] == "not_prepared"
    assert payload["preparation_required"] is True
    assert payload["boundary"]["workspace_file_mutation_allowed"] is False
    assert project_path.read_bytes() == original_project
    assert not (project_root / "outputs" / "navigation").exists()
    assert not (project_root / ".scout-connected-preparation").exists()


def test_scout_dashboard_living_closed_loop_contract() -> None:
    html = PAGE.read_text(encoding="utf-8")

    for marker in (
        'data-route="living"',
        '>Living<',
        'DASHBOARD_LIVING_PATH = "/admin/dashboard/living"',
        'function renderLivingPage()',
        'function scheduleLivingRefresh()',
        'data-living-action="run"',
        'data-living-action="approve"',
        'data-living-action="simulation"',
        'data-living-timeline="true"',
        '/emergency/mobile-approval-v0?living=1',
        'candidate-only / runtime truth=false',
        'production sent=false',
        'Record simulator receipt',
        'evaluation.evaluation_snapshot_id',
        'no real transport or delivery occurred',
        'projection.transport_attempt',
        'receipt?.source_attempt_id',
    ):
        assert marker in html

    assert 'scope === "living"' in html
    assert 'fetchJson(DASHBOARD_LIVING_PATH' in html
    assert 'postJson(`${DASHBOARD_LIVING_PATH}/scenarios/run`' in html
    assert 'postJson(`${DASHBOARD_LIVING_PATH}/approvals`' in html
    assert 'postJson(`${DASHBOARD_LIVING_PATH}/transport/simulations`' in html
    assert 'outcome: "simulated_receipt_recorded"' in html
    assert "simulated_delivery_verified" not in html


def test_scout_dashboard_ai_hat_trace_displays_actual_postprocess_mode() -> None:
    html = PAGE.read_text(encoding="utf-8")

    assert 'agentAiHatTraceValue(response, "ai_hat_postprocess_applied=")' in html
    assert "postprocess=${aiHatPostprocess}" in html


def test_scout_dashboard_body_index_fresh_project_has_no_fabricated_evidence(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        admin_api,
        "DEFAULT_DASHBOARD_BODY_INDEX_STORE_ROOT",
        tmp_path / "empty_store",
    )
    client = TestClient(create_admin_app())

    response = client.get(
        "/admin/dashboard/body-index?project_id=fresh_body_index_project"
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["schema_version"] == "scout_dashboard_body_index.v1"
    assert payload["project_id"] == "fresh_body_index_project"
    assert payload["import_status"] == "not_imported"
    assert payload["source_index"] == []
    expected_summary = {
        "scout_pace_coefficient": "unavailable",
        "energy_reserve": "unavailable",
        "vulnerability": "unavailable",
        "experience_trust": "unavailable",
        "score_percent": 0,
        "evidence_status": "unavailable",
    }
    for key, value in expected_summary.items():
        assert payload["summary"][key] == value
    assert payload["coverage_cards"] == [
        ["Health exports", "0", "no local HealthExport sources imported"],
        ["Walking sessions", "0", "no walking workouts imported"],
        ["GPX tracks", "0", "no route traces imported"],
        ["15-min windows", "0", "no sanitized pressure windows"],
        ["Provider metrics", "0", "no source-value metric families"],
    ]
    assert payload["pressure_timeline"] == []
    assert payload["provider_metrics"] == []
    assert payload["provider_metric_summaries"] == []
    assert all(row[1] == "pending" for row in payload["health_signals"])
    assert all("--" in row[2] for row in payload["health_signals"])
    assert payload["boundary"]["raw_health_payload_shared"] is False
    assert payload["boundary"]["raw_gpx_shared"] is False
    assert payload["boundary"]["phase1_runtime_safety_truth"] is False
    assert payload["boundary"]["safety_api_called"] is False
    assert payload["boundary"]["outbound_alert_sent"] is False

    html = PAGE.read_text(encoding="utf-8")
    for fabricated_value in (
        'value: "3.8 km/h"',
        'value: "410 m/h"',
        'value: "-34%"',
        'scout_pace_coefficient: "0.82"',
        '["Health exports", "3", "HealthAutoExport zip files"]',
        '["2018 long walk", "16 windows", "single GPX session", 33]',
    ):
        assert fabricated_value not in html


def test_scout_dashboard_body_index_all_invalid_import_stays_unavailable(
    tmp_path: Path,
    monkeypatch,
) -> None:
    source_dir = tmp_path / "InvalidHealthExport"
    source_dir.mkdir()
    with zipfile.ZipFile(source_dir / "invalid.zip", "w") as archive:
        archive.writestr("invalid.json", "{not valid json")
    monkeypatch.setattr(
        admin_api,
        "DEFAULT_DASHBOARD_BODY_INDEX_STORE_ROOT",
        tmp_path / "invalid_store",
    )
    client = TestClient(create_admin_app())

    response = client.post(
        "/admin/dashboard/body-index/import",
        json={
            "project_id": "invalid_body_index_project",
            "source_dir": str(source_dir),
            "confirm_import": True,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["import_status"] == "not_imported"
    assert payload["source_index"] == []
    assert payload["summary"]["evidence_status"] == "unavailable"
    assert payload["summary"]["scout_pace_coefficient"] == "unavailable"
    assert payload["summary"]["score_percent"] == 0
    assert payload["import_result"]["processed_source_count"] == 0
    assert payload["import_result"]["error_count"] == 1
    assert all(row[1] == "0" for row in payload["coverage_cards"])

    read_response = client.get(
        "/admin/dashboard/body-index?project_id=invalid_body_index_project"
    )
    assert read_response.status_code == 200
    assert read_response.json()["summary"] == payload["summary"]


def test_scout_dashboard_body_index_import_dedupes_and_sanitizes(
    tmp_path: Path,
    monkeypatch,
) -> None:
    source_dir = tmp_path / "HealthExport"
    source_dir.mkdir()
    _write_body_index_health_export_zip(
        source_dir / "HealthAutoExport-body-index-a.zip",
        day="2026-06-02",
        workout_id="walk-body-index-a",
        hour=8,
    )
    _write_body_index_health_export_zip(
        source_dir / "HealthAutoExport-body-index-b.zip",
        day="2026-06-03",
        workout_id="walk-body-index-b",
        hour=9,
    )
    monkeypatch.setattr(
        admin_api,
        "DEFAULT_DASHBOARD_BODY_INDEX_STORE_ROOT",
        tmp_path / "store",
    )
    client = TestClient(create_admin_app())

    rejected = client.post(
        "/admin/dashboard/body-index/import",
        json={"project_id": "test_body_index", "source_dir": str(source_dir)},
    )
    assert rejected.status_code == 400

    response = client.post(
        "/admin/dashboard/body-index/import",
        json={
            "project_id": "test_body_index",
            "source_dir": str(source_dir),
            "confirm_import": True,
        },
    )
    assert response.status_code == 200, response.text
    payload = response.json()

    assert payload["schema_version"] == "scout_dashboard_body_index.v1"
    assert payload["project_id"] == "test_body_index"
    assert payload["import_status"] == "imported"
    assert payload["summary"]["evidence_status"] == "available"
    assert payload["import_result"]["new_source_count"] == 2
    assert payload["import_result"]["duplicate_source_count"] == 0
    assert payload["import_result"]["processed_source_count"] == 2
    assert payload["import_result"]["error_count"] == 0
    assert payload["source_dir"] is None
    assert payload["source_provider"] == "local_health_export"
    assert all("imported_at" not in source for source in payload["source_index"])
    coverage = {row[0]: row[1] for row in payload["coverage_cards"]}
    assert coverage["Health exports"] == "2"
    assert coverage["Walking sessions"] == "2"
    assert coverage["GPX tracks"] == "2"
    assert int(coverage["15-min windows"]) > 0
    assert int(coverage["Provider metrics"]) >= 4
    assert "vo2_max" in payload["provider_metrics"]
    assert "walking_heart_rate_average" in payload["provider_metrics"]
    provider_metric_summaries = {
        metric["metric_name"]: metric for metric in payload["provider_metric_summaries"]
    }
    assert provider_metric_summaries["vo2_max"]["median_value"] == 37.0
    assert provider_metric_summaries["vo2_max"]["mean_value"] == 37.0
    assert provider_metric_summaries["vo2_max"]["sample_count"] == 4
    assert provider_metric_summaries["resting_heart_rate"]["median_value"] == 72.0
    health_signals = {row[0]: row for row in payload["health_signals"]}
    assert health_signals["VO2max Baseline"][2] == "median 37.0 / n=4"
    assert health_signals["Resting HR"][2] == "median 72.0 bpm / n=2"
    assert health_signals["HRV Baseline"][2].startswith("median ")
    assert health_signals["HR Pressure Windows"][2].endswith("windows")
    vo2_trend = health_signals["VO2max Baseline"][5]
    assert vo2_trend["direction"] == "mid"
    assert vo2_trend["position_percent"] == 50
    assert vo2_trend["min_label"] == "min 36.9"
    assert vo2_trend["baseline_label"] == "baseline 37.0"
    assert vo2_trend["average_label"] == "avg 37.0"
    assert vo2_trend["max_label"] == "max 37.1"
    assert "min-max range" in vo2_trend["summary"]
    pressure_trend = health_signals["HR Pressure Windows"][5]
    assert pressure_trend["min_label"] == "min 0"
    assert pressure_trend["max_label"].startswith("max ")
    assert payload["boundary"]["raw_health_payload_shared"] is False
    assert payload["boundary"]["raw_gpx_shared"] is False
    assert payload["boundary"]["exact_timestamps_shared"] is False
    assert payload["boundary"]["phase1_runtime_safety_truth"] is False
    assert payload["boundary"]["safety_api_called"] is False
    assert payload["boundary"]["outbound_alert_sent"] is False

    serialized = json.dumps(payload, ensure_ascii=False)
    assert "heartRateData" not in serialized
    assert "latitude" not in serialized
    assert "longitude" not in serialized
    assert "<trkpt" not in serialized
    assert "HealthAutoExport-body-index-a.zip" not in serialized
    assert "2026-06-02 08:00:00 +0800" not in serialized

    second_response = client.post(
        "/admin/dashboard/body-index/import",
        json={
            "project_id": "test_body_index",
            "source_dir": str(source_dir),
            "confirm_import": True,
        },
    )
    assert second_response.status_code == 200, second_response.text
    second_payload = second_response.json()
    assert second_payload["import_result"]["new_source_count"] == 0
    assert second_payload["import_result"]["duplicate_source_count"] == 2
    assert second_payload["import_result"]["processed_source_count"] == 2

    read_response = client.get("/admin/dashboard/body-index?project_id=test_body_index")
    assert read_response.status_code == 200
    read_payload = read_response.json()
    assert read_payload["coverage_cards"] == second_payload["coverage_cards"]
    assert read_payload["summary"]["evidence_status"] == "available"
    assert read_payload["source_dir"] is None
    assert all("imported_at" not in source for source in read_payload["source_index"])
    serialized_read = json.dumps(read_payload, ensure_ascii=False)
    for forbidden_value in (
        "heartRateData",
        "latitude",
        "longitude",
        "<trkpt",
        "HealthAutoExport-body-index-a.zip",
        "2026-06-02 08:00:00 +0800",
    ):
        assert forbidden_value not in serialized_read


def test_scout_dashboard_body_index_watch_imports_new_zip(
    tmp_path: Path,
    monkeypatch,
) -> None:
    project_id = "test_body_index_watch"
    source_dir = tmp_path / "HealthExportWatch"
    source_dir.mkdir()
    monkeypatch.setattr(
        admin_api,
        "DEFAULT_DASHBOARD_BODY_INDEX_STORE_ROOT",
        tmp_path / "watch_store",
    )
    client = TestClient(create_admin_app())

    rejected = client.post(
        "/admin/dashboard/body-index/watch/start",
        json={
            "project_id": project_id,
            "source_dir": str(source_dir),
            "interval_seconds": 1,
        },
    )
    assert rejected.status_code == 400

    response = client.post(
        "/admin/dashboard/body-index/watch/start",
        json={
            "confirm_watch": True,
            "project_id": project_id,
            "source_dir": str(source_dir),
            "interval_seconds": 1,
            "operator_alias": "watch_test",
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["running"] is True

    try:
        _write_body_index_health_export_zip(
            source_dir / "HealthAutoExport-watch-new.zip",
            day="2026-06-04",
            workout_id="walk-body-index-watch",
            hour=7,
        )
        deadline = time.monotonic() + 12
        payload: dict[str, object] | None = None
        status: dict[str, object] | None = None
        while time.monotonic() < deadline:
            status_response = client.get(
                f"/admin/dashboard/body-index/watch/status?project_id={project_id}"
            )
            assert status_response.status_code == 200
            status = status_response.json()
            read_response = client.get(
                f"/admin/dashboard/body-index?project_id={project_id}"
            )
            assert read_response.status_code == 200
            payload = read_response.json()
            coverage = {row[0]: row[1] for row in payload["coverage_cards"]}
            if coverage.get("Health exports") == "1":
                break
            time.sleep(0.25)
        assert payload is not None
        assert status is not None
        coverage = {row[0]: row[1] for row in payload["coverage_cards"]}
        assert coverage["Health exports"] == "1"
        assert coverage["Walking sessions"] == "1"
        assert status["running"] is True
        assert int(status["scan_count"]) >= 1
        assert int(status["import_count"]) >= 1
        assert status["last_result"]["new_source_count"] == 1
        serialized = json.dumps(payload, ensure_ascii=False)
        assert "heartRateData" not in serialized
        assert "HealthAutoExport-watch-new.zip" not in serialized
        assert "<trkpt" not in serialized
    finally:
        stop_response = client.post(
            "/admin/dashboard/body-index/watch/stop",
            json={"project_id": project_id},
        )
        assert stop_response.status_code == 200
        assert stop_response.json()["running"] is False


def test_scout_dashboard_serves_pace_fit_emergency_desktop_approval_ui() -> None:
    client = TestClient(create_admin_app())

    response = client.get("/admin/dashboard/emergency-approval-desktop-v0")

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert 'data-emergency-ui-version="v0"' in response.text
    assert 'data-dashboard-emergency-mode="desktop-only"' in response.text
    assert '<section class="mobile-device"' not in response.text
    assert 'data-emergency-surface="mobile"' not in response.text
    assert 'data-map-surface="mobile"' not in response.text
    assert 'data-evidence-frame="mobile"' not in response.text
    assert 'data-emergency-surface="desktop"' in response.text
    assert '<header class="desktop-header">' not in response.text
    assert "Scout Emergency Approval Console" not in response.text
    assert "Emergency Approval Desktop UI v0" not in response.text
    assert 'data-dashboard-sent-state="sent=false"' in response.text
    assert "sent=false" in response.text
    assert "safety_api_called: false" in response.text

    legacy_response = client.get("/admin/dashboard/emergency-mobile-approval-v0")
    assert legacy_response.status_code == 200
    assert 'data-dashboard-emergency-mode="desktop-only"' in legacy_response.text
    assert 'data-emergency-surface="mobile"' not in legacy_response.text


def test_scout_dashboard_documentation_records_active_change_log() -> None:
    doc = DOC.read_text(encoding="utf-8")

    assert "# Scout Dashboard v0.1" in doc
    assert "## Active Recording Rule" in doc
    assert "Status: active." in doc
    assert "continue recording until the user explicitly says to stop" in doc
    assert "## Implementation Record" in doc
    assert "Import New Trip Tab Added" in doc
    assert "GPX Import and Map Preparation Parameters Exposed" in doc
    assert "Reference GPX Inputs Merged" in doc
    assert "Documentation Recording Rule Added" in doc
    assert "Template Project Root and Material Root Clarified" in doc
    assert "Material Root Overlap With DTM and MCP Clarified" in doc
    assert "Optional Import Parameters Marked" in doc
    assert "Workspace Root and BBox Derivation Clarified" in doc
    assert "Workspace Root and Target Name Consolidated" in doc
    assert "Optional Parameters Collapsed Into Advanced Frame" in doc
    assert "Low-value Import Panels Condensed" in doc
    assert "Country Material Pool Tab Added" in doc
    assert "Route Context Briefing Regeneration And Product Copy Cleanup" in doc
    assert "Route Context Intelligence Spec-Aligned Briefing Generation" in doc
    assert "Route Briefing Trip-Only Product Copy Guard" in doc
    assert "Future LoRaWAN Sender Dashboard Placement" in doc
    assert "scout_lorawan_sender.py" in doc
    assert "Primary dashboard integration should be `MQTT / Observer Message`." in doc
    assert "sender/action lane" in doc
    assert "command candidates, queue state, dry-run/live send" in doc
    assert "it should not own the sender workbench" in doc
    assert "`Debug Message` may show sender status" in doc
    assert "must remain status-only and must not own the send button" in doc
    assert "send_sos" in doc
    assert "trigger_l4" in doc
    assert "change_safety_level" in doc
    assert "Pace Fit Body Index Dashboard" in doc
    assert "HealthExport Body Index UX Implemented" in doc
    assert "Body Index HealthExport Import Merge Button" in doc
    assert "Body Index Baseline Trend Arrows" in doc
    assert "Body Index Directory Watch Import" in doc


def test_scout_dashboard_contains_requested_navigation_contract() -> None:
    html = PAGE.read_text(encoding="utf-8")

    for expected in (
        "Home",
        "Features",
        "LBS",
        "Workspace",
        "Import New Trip",
        "Trip Intake",
        "Country Material Pool",
        "Debug Surface",
        "Agent",
        "Map",
        "Timeline Evidence",
        "Safety / Emergency",
        "Exploring for Six Axis",
        "Pace Dashboard",
        "Body Index",
        "Debug Message",
        "MQTT / Observer Message",
        "Settings / Configure",
    ):
        assert expected in html

    assert 'data-route="features-lbs"' in html
    assert 'data-route="features-workspace"' in html
    assert 'data-route="features-import-new-trip"' in html
    assert 'data-route="features-country-material-pool"' in html
    assert 'data-route="surface-pretrip"' not in html
    assert 'data-route="surface-admin"' not in html
    assert 'data-route="surface-debug"' in html
    assert 'data-route="outdoor-pace-fit-body-index"' in html
    assert 'data-route="emergency"' in html
    assert 'data-route="outdoor-pace-fit-emergency"' not in html


def test_scout_dashboard_points_to_current_chilai_workspace() -> None:
    html = PAGE.read_text(encoding="utf-8")

    assert 'const PROJECT_ID = "chilai_nanhua_day1_scoutAI";' in html
    assert 'new URLSearchParams(window.location.search).get("projectId")' in html
    assert "^[A-Za-z0-9_.-]+$" in html
    assert "const WORKSPACE_ROOT =" not in html
    assert 'fetchJson("/admin/dashboard/workspaces")' in html
    assert "resolved_project_root" in html
    assert "chilai_nanhua_day1 route map" not in html
    assert "Route overview map" in html
    assert 'basemapPolicy: "full-canonical"' in html


def test_scout_dashboard_embeds_only_the_debug_canonical_surface() -> None:
    html = PAGE.read_text(encoding="utf-8")

    assert "renderSurfaceFrame" in html
    assert 'id="surfaceFrame"' in html
    assert 'class="surface-frame"' in html
    assert 'src: surfaceSrc("/admin/pretrip")' not in html
    assert 'src: surfaceSrc("/admin")' not in html
    assert 'src: surfaceSrc("/admin/debug")' in html
    assert "projectId=${encodeURIComponent(projectId())}" in html
    assert "Admin Surfaces" not in html
    assert "Debug Surface" in html
    assert "Current Admin Surfaces" not in html
    assert "Open full page" in html


def test_dashboard_removes_pretrip_and_admin_surface_route_contracts() -> None:
    html = PAGE.read_text(encoding="utf-8")

    assert "surface-pretrip" not in html
    assert "surface-admin" not in html
    assert 'title: "Pre-trip Planning"' not in html
    assert 'title: "Admin After-Action"' not in html
    assert "Pre-trip、Admin 與 Debug canonical surface" not in html
    assert 'title: "Debug canonical surface"' in html
    assert 'const knownRoute = routeMeta[route] || SIX_FORCES.some' in html
    assert '`${window.location.pathname}${window.location.search}#home`' in html


def test_scout_dashboard_data_fetches_have_timeout_fallback() -> None:
    html = PAGE.read_text(encoding="utf-8")

    assert "const FETCH_TIMEOUT_MS = 20000;" in html
    assert "const ASSISTANT_QUERY_TIMEOUT_MS = 240000;" in html
    assert "const PRETRIP_PROJECT_FETCH_TIMEOUT_MS = 180000;" in html
    assert "new AbortController()" in html
    assert "const timeoutMs = Number(options.timeoutMs) || FETCH_TIMEOUT_MS;" in html
    assert "signal: controller.signal" in html
    assert "window.clearTimeout(timer)" in html
    assert "{ timeoutMs: PRETRIP_PROJECT_FETCH_TIMEOUT_MS }" in html
    assert "setRoute(routeFromHash());" in html
    assert "loadWorkspaceCatalog().finally(() => loadData()).finally(() =>" in html
    assert "routeUsesEmbeddedFrame(state.route)" in html
    assert 'return route === "map" || route === "agent" || route.startsWith("surface-");' in html
    assert "routeUsesWideFrame(route)" in html
    assert 'return route === "agent" || route === "debug" || route === "diagnostic" || route === "runtime-audit" || route === "emergency" || route === "outdoor-route-context" || route === "outdoor-pace-fit" || route === "outdoor-pace-fit-body-index";' in html
    assert "routeUsesFullFrame(route)" in html
    assert 'return route === "map";' in html
    project_loader = html.split("async function loadProjectData()", 1)[1].split(
        "async function loadBriefingData()",
        1,
    )[0]
    assert "/debug-projection`" not in project_loader


def test_scout_dashboard_agent_tab_posts_to_same_origin_assistant_api() -> None:
    html = PAGE.read_text(encoding="utf-8")

    assert 'id="dashboardAgent"' in html
    assert 'data-agent-query-path="/assistant/query"' in html
    assert 'const ASSISTANT_STATUS_PATH = "/assistant/status";' in html
    assert 'const ASSISTANT_QUERY_PATH = "/assistant/query";' in html
    assert 'id="agentTranscript"' in html
    assert 'id="agentComposer"' in html
    assert 'id="agentQuestionInput"' in html
    assert 'id="agentAskButton"' in html
    assert 'id="agentProjectChip"' in html
    assert 'id="agentFallbackToggle"' in html
    assert 'id="agentRawEvalToggle"' in html
    assert "AI HAT+2 fallback" in html
    assert "Facts-only model eval" in html
    assert "agentUseAiHatFallback" in html
    assert "agentUseAiHatRawEval" in html
    assert "width: fit-content;" in html
    assert "max-width: min(900px, 86%);" in html
    assert "border: 0;" in html
    assert ".agent-message.user .agent-message-body" in html
    assert 'class="agent-message-body"' in html
    assert "function displayAgentAnswer(answer)" in html
    assert ".replace(/^結論[:：]\\s*/u, \"\")" in html
    assert "response?.evidence_backed_answer" in html
    assert "response?.local_model_answer" in html
    assert "AI HAT+2 原始回答（grounding 失敗，僅供品質檢查）" in html
    assert "回答（AI HAT+2 grounded repair）" in html
    assert "回答（AI HAT+2 synthesized from workspace facts）" in html
    assert "回答（AI HAT+2 staged missing-context synthesis）" in html
    assert "回答（AI HAT+2 + field-state-short-answer skill）" in html
    assert "skill using：${aiHatSkillId" in html
    assert "function agentAiHatSkillId(response)" in html
    assert "ai_hat_skill_id=" in html
    assert "回答（AI HAT+2 action + verified Scout evidence）" not in html
    assert "AI HAT+2 模型原始輸出（typed decision 不算自然語言回答）" in html
    assert "AI HAT+2 typed decision token" in html
    assert "AI HAT+2 action token" in html
    assert "if (aiHatActionToken)" in html
    assert "Verified Scout evidence：已用於上方 hybrid answer" not in html
    assert '"typed_decision_only"' in html
    assert '"typed_decision_with_verified_evidence"' in html
    assert '"typed_missing_context_action_only"' in html
    assert "function agentAiHatTypedDecision(response)" in html
    assert "function agentAiHatActionToken(response)" in html
    assert "ai_hat_typed_decision=" in html
    assert "ai_hat_action_token=" in html
    assert "模型未產生獨立回答（AI HAT+2 copied grounding reference）" in html
    assert "AI HAT+2 原始回答（未通過 grounding，不計成功）" not in html
    assert "模型未成功回答（工具摘要另列）" in html
    assert "不能算作模型答題成功" in html
    assert "function agentAiHatGenerationMode(response)" in html
    assert "function agentAnswerLooksLikeReferenceCopy(answer, reference)" in html
    assert "ai_hat_generation_mode=" in html
    assert "function agentDeterministicFallbackOnly(response)" in html
    assert "deterministic_tool_fallback_only=true" in html
    assert "segment_missing_display_geometry_count" in html
    assert "segment_missing_distance_count" in html
    assert "Scout grounding reference（工具摘要，不取代本地模型回答）" in html
    assert "Scout grounding reference" in html
    assert "quality verdict：AI HAT+2 evidence-prompted answer did not preserve required Scout evidence" in html
    assert "near-copy/subset of the deterministic Scout grounding reference" in html
    assert "typed decision 只能算分類成功" in html
    assert "action token 不能算作回答，也不會套用固定句型" in html
    assert "transparent Scout evidence lock" not in html
    assert "missing|缺|stale|過期" not in html
    assert "(?:缺少|過期|过期)" in html
    assert "AI HAT+2 raw answer（未採用：grounding failed）" not in html
    assert "useEvidenceAsAnswer" not in html
    assert (
        'displayAgentAnswer(response?.answer || "(empty assistant answer)")'
        in html
    )
    assert "response?.evidence_backed_answer || response?.answer" not in html
    assert "Pydantic AI read-only model interpretation" in html
    assert "AI HAT+2 ${observability.local_model_name}" in html
    assert "observability.provider_class" not in html
    assert "function bindAgentChatControls()" in html
    assert "function ensureAgentChat()" in html
    assert "function submitAgentQuestion()" in html
    assert "postJson(" in html
    assert "ASSISTANT_QUERY_PATH," in html
    assert "{ timeoutMs: ASSISTANT_QUERY_TIMEOUT_MS }" in html
    assert "request timed out after" in html
    assert 'surface: "pretrip"' in html
    assert "project_id: projectId()" in html
    assert 'runtime_preference: "cloud"' in html
    assert 'payload.runtime_preference = "ai_hat_plus_2_fallback";' in html
    assert "payload.ai_hat_raw_eval = Boolean(state.agentUseAiHatRawEval);" in html
    assert "AI HAT+2 本地模型回答" in html
    assert "prompt-contract=${aiHatPromptContract}" in html
    assert "answer-contract=${aiHatAnswerContract}" in html
    assert "few-shot=${aiHatFewShotSource}:${aiHatFewShotCount}" in html
    assert "few-shot-topic=${aiHatFewShotQuestion}" in html
    assert "endpoint-response=${aiHatEndpointResponse}" in html
    assert "eval-tokens=${aiHatEvalCount}" in html
    assert "selected-call=${aiHatSelectedCall}" in html
    assert "sampling=${aiHatSampling}" in html
    assert "response?.local_model_attempts" in html
    assert "model attempt ${attempt.call_index}" in html
    assert "answer-template=${aiHatAnswerTemplate}" in html
    assert "本地模型只收到 facts-only evidence brief，沒有預寫答案" in html
    assert "function agentAiHatTraceValue(response, prefix)" in html
    assert "meta: state.agentUseAiHatFallback ? [\"AI HAT+2 fallback requested\"] : []" in html
    assert "meta: [`project=${projectId()}`, \"surface=pretrip\"]" not in html
    assert "Same-origin Scout AI conversation through /assistant/query" in html
    assert "No live safety" in html
    assert "Dashboard Scout AI API · /assistant/query" in html
    assert "127.0.0.1:8765" not in html
    assert 'contentGrid?.classList.toggle("is-frame-wide", frameWide);' in html
    assert ".content-grid.is-frame-wide .evidence-drawer" in html
    assert "dashboardAgent.hidden = false;" in html
    assert "dashboardAgent.focus?.({ preventScroll: true });" in html


def test_scout_dashboard_workspace_tab_summarizes_project_stats() -> None:
    html = PAGE.read_text(encoding="utf-8")

    assert "function workspaceStats()" in html
    assert "function renderWorkspaceStatsPanels(stats)" in html
    assert 'data-workspace-stats="true"' in html
    for label in (
        "Route Statistics",
        "Project Counts",
        "Lifecycle Times",
        "Route length",
        "Route points",
        "Elevation range",
        "Reference tracks",
        "Checkpoints",
        "Segments",
        "Terrain tiles",
        "Review queue",
        "Evidence refs",
        "Imported",
        "Layers prepared",
        "Runtime exported",
        "Runtime loaded",
        "Data source",
    ):
        assert label in html

    assert "formatDistanceKm(numberValue(route.distance_m" in html
    assert 'if (value === null || value === undefined || value === "") return "--";' in html
    assert "formatDateTime(" in html
    assert "latestDebugEventTime" in html
    assert "workspaceEvidenceRefCount(project)" in html
    assert "project.import_manifest?.imported_at" in html
    assert "project.layer_preparation?.prepared_at" in html
    assert "state.pretripDataProjectId || projectId()" in html


def test_scout_dashboard_workspace_tab_exposes_structure_cache_and_operations() -> None:
    html = PAGE.read_text(encoding="utf-8")
    workspace_page = html.split("function renderWorkspacePage()", 1)[1].split(
        "function renderWorkspaceStructurePanels()",
        1,
    )[0]
    operation_console = html.split(
        "function renderWorkspaceOperationConsole()",
        1,
    )[1].split("function countryMaterialPools()", 1)[0]

    for function_name in (
        "renderWorkspaceStructurePanels",
        "workspaceStructureRows",
        "renderWorkspaceCachePanels",
        "workspaceCacheRows",
        "renderWorkspaceOperationConsole",
        "bindWorkspaceControls",
        "loadWorkspaceCatalog",
        "loadWorkspaceOperationRequests",
        "resolvedWorkspaceRoot",
        "formatTtl",
        "formatBoolean",
    ):
        assert f"function {function_name}" in html

    for label in (
        "Workspace Structure",
        "Material Index",
        "Workspace Health",
        "Cached Material",
        "Cached TTL",
        "Cache Refs",
        "Workspace Operations",
        "Project root",
        "Source inbox",
        "Normalized route",
        "Import manifest",
        "Layer manifest",
        "Review queue",
        "Runtime handoff",
        "Imagery tiles",
        "Raster OCR",
        "OSM PBF",
        "OSM PBF TTL",
        "CWA TTL",
        "GEE TTL",
        "Weather cacheable",
    ):
        assert label in html

    for action in ("transfer", "pack", "restore", "delete"):
        assert f'data-workspace-action="{action}"' in html

    assert 'id="workspaceCloneTargetInput"' in html
    assert 'id="workspaceCloneProject"' in html
    assert 'data-workspace-clone="true"' in html
    assert 'data-workspace-structure="true"' in html
    assert 'data-workspace-cache="true"' in html
    assert 'data-workspace-operations="true"' in html
    assert 'id="workspaceOperationStatus"' in html
    assert 'id="workspaceRedirectProjectInput"' in html
    assert 'id="workspaceSwitchProject"' in html
    assert 'id="workspaceRefreshExternalEvidence"' in html
    assert "operator-triggered" in html
    assert "Clone creates a new target with one clean GPX import" in html
    assert "refuses to overwrite an existing target" in html
    assert "/clone`" in html
    assert "confirm_clone: true" in html
    assert "WORKSPACE_CLONE_TIMEOUT_MS" in html
    assert "Delete requires an explicit destructive approval outside this dashboard." in html
    assert 'fetchJson("/admin/dashboard/workspaces")' in html
    assert "/operation-requests" in html
    assert 'operation: operationName' in html
    assert "confirm_record: true" in html
    assert "triggerDashboardConnectedPreparation(\"workspace-operator-refresh\"" in html
    assert (
        "Dashboard startup and status GETs read cached evidence only and never "
        "schedule a writer."
        in html
    )
    assert "After an explicit “Refresh evidence” or Scout AI weather refresh" in html
    assert (
        "The current published snapshot stays readable while refresh is running;"
        in html
    )
    assert "CWA, GEE and Overpass stay refreshable" in html
    assert "geology stays a runtime provider" in html
    assert "summaryCache.imagery_tile_cache_seed_tiles_seen" in html
    assert "summaryCounts.raster_label_ocr_label_count" in html
    assert "planned / ${formatInteger(imageryReady)} ready" in html
    assert "candidate labels / ${formatInteger(ocrHits)} cached" in html
    assert "summaryCache.imagery_tile_cache_manifest_ref" in html
    assert "summaryCache.raster_label_ocr_cache_ref" in html
    assert "state.connectedPreparation?.nextRunAt" in html
    assert "preparation.publicationStatus" in html
    assert "preparation.recoveryJournalStatus" in html
    assert "status.crossProcessLocking === true" in html
    assert "status.recoveryJournalStatus" in html
    assert "Cross-process lock" in html
    assert "Recovery journal" in html
    assert "after current refresh completes" in html
    assert 'localStorage.setItem("scout.dashboardProjectId", nextProjectId)' in html
    assert 'url.searchParams.set("projectId", nextProjectId)' in html
    assert 'url.hash = "features-workspace";' in html
    assert "validateWorkspaceSelection(nextProjectId)" in html
    assert "const WORKSPACE_ROOT =" not in html
    assert "void loadConnectedPreparationStatus();" in html
    assert 'triggerDashboardConnectedPreparation("dashboard-open")' not in html
    assert workspace_page.index("renderWorkspaceOperationConsole()") < workspace_page.index(
        "renderWorkspaceStatsPanels(stats)"
    )
    assert 'renderMetricPanel("Importer"' not in workspace_page
    assert 'renderMetricPanel("Workspace Edits"' not in workspace_page
    assert 'renderMetricPanel("Runtime Handoff"' not in workspace_page
    for label in (
        "Clone",
        "Transfer",
        "Package",
        "Restore",
        "Delete review",
        "Import trip",
        "Refresh evidence",
        "Open workspace",
    ):
        assert f">{label}</button>" in operation_console
    assert "white-space: normal;" in html
    assert "overflow-wrap: anywhere;" in html


def test_scout_dashboard_import_new_trip_tab_contract() -> None:
    html = PAGE.read_text(encoding="utf-8")

    for function_name in (
        "renderImportNewTripPage",
        "renderImportTripPreflight",
        "renderImportTripPipeline",
        "renderImportSelectField",
        "importTripProjectId",
        "importTripDefaultLayerIds",
        "setImportTripStatus",
        "bindImportTripControls",
        "splitImportReferenceGpxSources",
        "classifyImportReferenceGpxSources",
    ):
        assert f"function {function_name}" in html

    for label in (
        "Features / Import New Trip",
        "Import New Trip",
        "Optional Parameters",
        "GPX Import Defaults",
        "Map Preparation Defaults",
        "Defaults are used when this frame stays collapsed.",
        "Import Pipeline",
        "Validate Intake",
        "Preview Import",
        "Create Workspace",
        "Open Workspace",
        "operator-triggered",
        "no live safety",
        "boundary metadata",
        "derived routing",
        "GPX required",
        "32 layers",
        "candidate export",
        "no outbound",
        "GIS repro-only",
        "Target name",
        "Project root",
        "Country material pool",
        "Material Pool",
        "material pool",
    ):
        assert label in html

    for marker in (
        'data-import-new-trip="true"',
        'data-import-trip-parameters="true"',
        'data-map-preparation-parameters="true"',
        'data-import-trip-preflight="true"',
        'data-import-trip-pipeline="true"',
        'class="import-context-panel"',
        'class="import-guard-strip"',
        'id="importTripIdInput"',
        'id="importGoldenRouteGpxPath"',
        'id="importWorkspaceRoot"',
        'id="importTargetNameInput"',
        'id="importTripStatus"',
        'data-import-trip-action="validate"',
        'data-import-trip-action="preview"',
        'data-import-trip-action="create"',
        'data-import-trip-action="open"',
        'class="panel optional-parameters-frame"',
    ):
        assert marker in html

    for field_id in (
        "importReferenceGpxSources",
        "importWorkspaceRoot",
        "importTargetNameInput",
        "importTemplateProjectRoot",
        "importMaterialRoot",
        "importDtmDirs",
        "importMcpNamedPointEvidence",
        "importProfile",
        "importStage",
        "importCheckpointSpacingM",
        "importMaxReferenceDisplayPoints",
        "importMaxReasonableGpxSpeedKmh",
        "importMaxPreviousGpxSpeedRatio",
        "importOverwriteWorkspace",
        "prepareLayersList",
        "prepareBBox",
        "prepareRouteEvidenceBundle",
        "prepareRouteCorridorM",
        "prepareReferenceTrackCorridorM",
        "prepareLayersProfile",
        "prepareLayersNetworkMode",
        "prepareAllowNetworkFetch",
        "prepareAiMode",
        "prepareAiOutputPolicy",
        "prepareImageryMinZoom",
        "prepareImageryMaxZoom",
        "prepareSeedImageryCache",
        "prepareImageryProviderAllowsOfflinePrefetch",
        "prepareImagerySeedMaxTiles",
        "prepareImageryCacheFallbackProjectIds",
        "prepareOsmPbfPath",
        "prepareOsmPbfSourceUrl",
        "prepareOsmPbfCacheTtlDays",
        "prepareOsmiumBin",
        "preparePreparedAt",
    ):
        assert field_id in html

    for parameter_label in (
        "Golden route GPX path",
        "Reference GPX directory or paths",
        "Checkpoint spacing (m)",
        "Max reference display points",
        "Max reasonable GPX speed (km/h)",
        "Max previous speed ratio",
        "Layer ids",
        "Route evidence bundle",
        "Route corridor (m)",
        "Reference track corridor (m)",
        "Network mode",
        "AI mode",
        "Imagery min zoom",
        "Imagery max zoom",
        "OSM PBF cache TTL days",
    ):
        assert parameter_label in html

    assert "(optional)" not in html
    assert "Golden route GPX path (optional)" not in html
    assert "Target workspace (optional)" not in html
    assert "Project root (optional)" not in html
    assert "Import Boundary" not in html
    assert "Workspace Routing" not in html
    assert "Preflight Checklist" not in html
    assert "Layer Preparation Target" not in html
    assert "Runtime Handoff Guard" not in html
    assert "Evidence Drawer" not in html
    assert '<details class="panel optional-parameters-frame" data-import-trip-parameters="true">' in html
    assert '<details class="panel optional-parameters-frame" data-import-trip-parameters="true" open>' not in html
    assert 'id="importTripWorkspaceInput"' not in html
    assert 'id="prepareLayersWorkspaceRoot"' not in html
    assert 'id="prepareProjectRoot"' not in html

    assert 'if (route === "features-import-new-trip") return renderImportNewTripPage();' in html
    assert "importTripDraft" in html
    assert "goldenRouteGpx: goldenRouteInput.value.trim()" in html
    assert "countryMaterialPool: countryPoolInput.value || \"TW\"" in html
    assert "referenceGpxSources: fieldValue(\"importReferenceGpxSources\")" in html
    assert "targetName: targetNameValue()" in html
    assert "/import-gpx-preview" in html
    assert "/import-gpx`" in html
    assert "confirm_import: true" in html
    assert "max_previous_gpx_speed_ratio: maxPreviousSpeedRatio" in html
    assert "importPayload.material_root = materialRoot" in html
    assert "importPayload.dtm_dirs = dtmDirs" in html
    assert "importPayload.mcp_named_point_evidence = mcpNamedPointEvidence" in html
    assert "imagery,osm,overpass,terrain" in html
    assert "mcp,pois,hazards,corridors,retreat,route-notes" in html
    assert "validateWorkspaceSelection(nextProjectId)" in html
    assert 'id="importWorkspaceRoot"' in html
    assert 'placeholder="Load the server workspace catalog" readonly' in html
    assert "workspace_root: workspaceRoot" not in html
    assert "workspaceRoot: workspaceRootValue()" in html
    assert "prepareWorkspaceRoot: workspaceRootValue()" in html
    assert "prepareProjectRoot: derivedProjectRoot()" in html
    assert "importTripProjectRoot(workspaceRoot, targetName)" in html
    assert "prepareLayers: fieldValue(\"prepareLayersList\") || importTripDefaultLayerIds()" in html
    assert "fieldValue(\"prepareLayersList\") || importTripDefaultLayerIds()" in html
    assert 'value="${escapeHtml(draft.goldenRouteGpx || "")}"' in html
    assert "Reference GPX sources must be absolute paths." in html
    assert "Use either one directory path or a list of .gpx absolute paths." in html
    assert "1 reference GPX directory" in html
    assert "explicit GPX paths" in html
    assert "At least one map preparation layer id is required." in html
    assert "GPX import numeric parameters must be greater than 0." in html
    assert "Map preparation corridor parameters must be greater than 0." in html
    assert 'bindImportTripControls();' in html
    assert 'bindCountryMaterialPoolControls();' in html
    assert 'localStorage.setItem("scout.dashboardProjectId", nextProjectId)' in html
    assert 'url.searchParams.set("projectId", nextProjectId)' in html
    assert 'url.hash = "features-workspace";' in html
    assert "Trip id must use letters, numbers, underscore, dash or dot only." in html
    assert "Target name must use letters, numbers, underscore, dash or dot only." in html
    assert "importReferenceDirectory" not in html
    assert "importReferenceGpxPaths" not in html


def test_scout_dashboard_country_material_pool_contract() -> None:
    html = PAGE.read_text(encoding="utf-8")

    for function_name in (
        "countryMaterialPools",
        "countryMaterialPoolByCode",
        "countryMaterialPoolDefaults",
        "renderCountryMaterialPoolPage",
        "materialPoolCell",
        "renderMaterialResourceCard",
        "renderMaterialProviderRow",
        "bindCountryMaterialPoolControls",
    ):
        assert f"function {function_name}" in html

    for label in (
        "Features / Country Material Pool",
        "country-scoped material and API provider defaults",
        "Country Material Pool",
        "Material Classes",
        "Route Context References",
        "API / Provider Matrix",
        "Import Defaults",
        "Map Preparation Uses",
        "Taiwan",
        "Japan",
        "Global Fallback",
        "DTM",
        "Base Maps",
        "Government Sites",
        "Weather API",
        "Geology API",
        "Marine API",
        "Open Data Entry",
        "CWA",
        "JMA",
        "GSI Maps",
        "NLSC EMAP",
        "Central Geological Survey",
        "林業及自然保育署自然步道資料",
        "台灣山林悠遊網開放資料",
        "臺灣登山申請一站式服務網",
        "國家公園路線開放狀態",
        "內政部國土測繪中心 DEM / DTM / 地形圖",
        "中央氣象署 CODiS / 開放資料",
        "NCDR 災害潛勢資料",
        "消防署山域事故救援案件",
        "TBN 台灣生物多樣性網絡",
        "中研院臺灣百年歷史地圖",
        "尋路・循路－臺灣原住民族古道空間資訊網",
        "國家文化記憶庫",
        "臺灣記憶",
        "地質雲",
        "魯地圖",
        "健行筆記",
        "Hikingbook",
        "PTT Hiking",
        "登山補給站",
        "rescue_training_reference",
        "community_media_evidence",
        "country-specific Geofabrik extract",
        "material_root",
        "dtm_dirs",
        "osm_pbf_source_url",
        "weather_provider",
        "candidate evidence only",
        "no live safety",
    ):
        assert label in html

    for marker in (
        "const COUNTRY_MATERIAL_POOLS = [",
        'data-country-material-pool="true"',
        'data-country-material-code="${escapeHtml(candidate.code)}"',
        'role="tablist"',
        'class="material-pool-layout"',
        'class="material-resource-grid"',
        'data-route-context-references="true"',
        'class="material-provider-table"',
        'if (route === "features-country-material-pool") return renderCountryMaterialPoolPage();',
        "state.activeCountryMaterialPool = code;",
        "countryMaterialPoolDefaults(countryPoolInput.value)",
        "materialRoot: \"\"",
        "dtmDirs: \"\"",
        "osmPbfSourceUrl: \"\"",
    ):
        assert marker in html

    assert "Japan providers; no CWA" in html
    assert "routeContextSources" in html
    assert "These P0/P1 entries come from specs/scout-route-context-layer and source-catalog.md." in html
    assert "catalog entries are not evidence by themselves" in html
    assert "This page sets default hints for import and layer preparation." not in html
    assert "It does not fetch, mutate workspace files, load runtime packages, or change safety truth." not in html


def test_scout_dashboard_timeline_evidence_uses_pretrip_tree_categories() -> None:
    html = PAGE.read_text(encoding="utf-8")

    assert 'const PRETRIP_DATA_PROJECT_ID = "chilai_nanhua_day1";' in html
    assert "function pretripDataProjectIds()" in html
    assert "fetchFirstPretripJson" in html
    assert "renderPretripEvidencePanel" in html
    assert "pretripEvidenceGroups" in html
    assert "const overpassTimelineItems = [" in html
    assert "const overpassCategoryItems = (categoryId) =>" in html
    assert "const overpassCategoryCount = (categoryId) =>" in html
    assert 'overpassCategoryItems("overpass_hiking_route")' in html
    assert 'displayCount: overpassCategoryCount("overpass_hiking_route")' in html
    assert "source checked · no matches" in html
    assert "prepared · no candidates" in html
    assert "completed GPX not imported" in html
    assert "const displayCountLabel = zeroState ? zeroState : countLabel;" in html
    assert 'zeroState: view.capability_timeline_import ? "no completed edges" : "not imported"' in html
    assert 'const COMPLETED_TRIP_RECORDINGS_PATH = "/admin/post-analysis/completed-trip-recordings";' in html
    assert "function completedTripRecordingsPath()" in html
    assert "projectId=${encodeURIComponent(state.pretripDataProjectId || projectId())}" in html
    assert "completedTripRecordingSelectPath(safeRecordingId)" in html
    assert "function renderCompletedGpxLifecycle()" in html
    assert "async function loadCompletedTripRecordings()" in html
    assert "async function activateCompletedTripRecording(recordingId)" in html
    assert 'data-completed-gpx-action="refresh"' in html
    assert 'data-completed-gpx-recording-id="${escapeHtml(recording.recording_id)}"' in html
    assert 'data-pretrip-evidence-source="${escapeHtml(sourceProject)}"' in html
    for tab_id, label in (
        ("default", "CP / Timeline"),
        ("map_risk", "Map / Risk"),
        ("completed", "Completed GPX"),
        ("review", "Review / Queue"),
        ("info", "Info / Other"),
    ):
        assert f'id: "{tab_id}"' in html
        assert label in html

    for group_name in (
        "Evidence Timeline",
        "Reference Segment Timing",
        "Checkpoints",
        "AI GIS CP",
        "GIS CP Areas",
        "Major Critical Points",
        "Boss Points",
        "Mileage Tags",
        "Overpass Trail Corridors",
        "Overpass Terrain Risk",
        "OSM Trail Network",
        "Risk Score",
        "Baseline Risk",
        "Calibrated Heat",
        "Risk Delta",
        "Environmental Risk Derivatives",
        "CWA QPF",
        "CWA Weather",
        "Soil Moisture",
        "Antecedent Rain",
        "Segments",
        "Retreat Routes",
        "Reference GPX",
        "Capability Timeline",
        "Rest Intervals",
        "Info Sections",
        "Review Groups",
        "Review Queue",
    ):
        assert group_name in html

    assert 'data-evidence-tab="${escapeHtml(tab.id)}"' in html
    assert 'rerenderEvidenceContext("timeline", selectedTab);' in html
    assert 'rerenderEvidenceContext("map", selectedTab);' in html
    assert 'if (state.route !== "map") {' in html
    assert 'window.location.hash = "map";' in html
    assert "focusDashboardMapEvidence(sourceId, attempt + 1);" in html


def test_scout_dashboard_map_tab_uses_pretrip_map_only_surface() -> None:
    html = PAGE.read_text(encoding="utf-8")
    pretrip_html = PRETRIP_PAGE.read_text(encoding="utf-8")

    assert 'if (route === "map") {' in html
    assert "ensurePretripMapFrame()" in html
    assert "function ensurePretripMapFrame()" in html
    assert "bindPretripMapOnlyFrame" in html
    assert "applyPretripMapOnlyFrame" in html
    assert "scout-dashboard-map-only-style" in html
    assert 'id="dashboardMap"' in html
    assert html.count('id="dashboardMap"') == 1
    assert html.count('id="dashboardMapStatus"') == 1
    for preview_id in ("overview-map", "lbs-map", "permission-map"):
        assert f'id: "{preview_id}"' in html
    assert 'data-dashboard-context-map="${escapeHtml(mode)}"' in html
    assert 'id="pretripMapFrame"' in html
    assert 'data-map-mode="pretrip-map-only"' in html
    assert 'data-map-source="/admin/pretrip"' in html
    assert 'hidden aria-hidden="true" tabindex="-1"' in html
    assert 'frame.dataset.projectId === currentProjectId' in html
    assert 'frame.dataset.mapOnlyBound' in html
    assert "is-frame-full" in html
    assert 'surfaceSrc("/admin/pretrip")' in html
    assert "data-map-connected" in html
    assert "pre-trip map only" in html
    assert 'id="dashboardMapEvidence"' in html
    assert "renderMapEvidenceRail" in html
    assert "Map Evidence" in html
    assert "mapEvidenceCollapsed" in html
    assert "dashboardMapEvidenceStartsCollapsed" in html
    assert "mapEvidenceCollapsed: dashboardMapEvidenceStartsCollapsed()," in html
    assert "data-map-evidence-toggle" in html
    assert 'aria-label="${collapsed ? "Expand Map Evidence" : "Collapse Map Evidence"}"' in html
    assert 'rail.classList.toggle("is-collapsed", collapsed);' in html
    assert "map-evidence-rail.is-collapsed" in html
    assert "focusDashboardMapEvidence" in html
    assert "pretripEvidenceGroupOpen" in html
    assert (
        'renderPretripEvidenceGroup(group, index, {context: "map", tabId: activeTab})'
        in html
    )
    assert 'add("map_risk", "Segments", view.segments' in html
    assert "scheduleMapEvidenceFocusRetry" in html
    assert "const MAP_EVIDENCE_FOCUS_MAX_ATTEMPTS = 45;" in html
    assert "pretripMapHasRenderedTargets" in html
    assert "Loading pre-trip timeline evidence for map focus." in html
    assert "function pretripEvidenceGroupOpen(_group, _index)" in html
    assert "mapWindow.focusMapFor" in html
    assert "mapWindow.selectEvidence" in html
    assert "mapWindow.scoutPretripMapRendererBridge" in html
    assert "snapshot.feature_count" in html
    assert "const hasRenderedMapLibre = mapLibreSnapshot?.state === \"ready\"" in html
    assert "state.pendingMapEvidenceFocusId === pendingFocusId" in html
    assert "data-map-evidence-source" in html
    assert "data-map-target-ids" in html
    assert 'const mapToolRight = state.mapEvidenceCollapsed ? "14px" : "418px";' in html
    assert 'const compactMapOnlyLayout = window.matchMedia?.("(max-width: 620px)")?.matches === true;' in html
    assert 'doc.querySelector(".layer-menu")?.toggleAttribute("open", !compactMapOnlyLayout);' in html
    assert 'doc.querySelector(".layer-advanced")?.toggleAttribute("open", !compactMapOnlyLayout);' in html
    assert "right: ${mapToolRight} !important;" in html
    assert "dashboardMapOnly" in html
    assert "mapOnlyReady" in html
    assert "grid-template-rows: minmax(0, 1fr);" in html
    assert ".dashboard-frame" in html
    assert 'dashboardShell?.classList.toggle("is-frame-full", frameFull);' in html
    assert 'document.body.classList.toggle("is-frame-full", frameFull);' in html
    assert "body.is-frame-full" in html
    assert ".dashboard-shell.is-frame-full .dashboard-sidebar" in html
    assert "height: 100%;" in html
    assert "min-height: 0;" in html
    assert "#readinessStrip" in html
    assert ".route-pane" in html
    assert ".detail-pane" in html

    assert "const MAX_RENDERED_SEGMENT_POINTS = 80;" in html
    assert 'basemapPolicy: "full-canonical"' in html
    assert "const RASTER_SOURCE_LAYER_DEFINITIONS = [" in pretrip_html
    assert "const MAP_LAYER_RANKS = {" in pretrip_html
    assert (
        "...Object.fromEntries(SCOUT_LAYER_IDS.map((layerId) => "
        '[layerId, layerId !== "osm"]))'
    ) in html
    assert "...WEATHER_LAYER_DEFAULTS" in html
    assert 'data-layer="osm" checked' not in pretrip_html
    assert '<input type="checkbox" data-layer="osm"> OSM' in pretrip_html
    assert "function buildDashboardSegmentPaths(rawSegments, bounds)" in html
    assert "segment.display_geometry || {}" in html
    assert "display.coordinate_segments" in html
    assert "segmentPaths: buildDashboardSegmentPaths(state.project?.segments, bounds)" in html
    segment_branch = html.split('if (layerId === "segments") {', 1)[1].split(
        'if (["reference-tracks", "retreat"].includes(layerId)) {',
        1,
    )[0]
    assert "mapData.segmentPaths" in segment_branch
    assert 'data-segment-id="${escapeHtml(segment.id)}"' in segment_branch
    assert 'stroke="#00d4ff"' in segment_branch
    assert 'stroke-width="5.6"' in segment_branch
    assert 'stroke-dasharray="7 4"' in segment_branch
    assert "mapData.routePath" not in segment_branch


def test_dashboard_spatial_maps_share_the_canonical_map_navigation_contract() -> None:
    html = PAGE.read_text(encoding="utf-8")

    for marker in (
        "function renderDashboardMapControls(",
        "function renderDashboardMapViewport(",
        "function createDashboardMapViewportController(",
        "function bindDashboardMapViewports()",
        "bindDashboardMapViewports();",
        'data-map-control="zoom-in"',
        'data-map-control="zoom-out"',
        'data-map-control="reset"',
        'data-map-control="pan"',
        'data-map-control="box-zoom"',
        'data-map-zoom-level',
        'addEventListener("pointerdown"',
        'addEventListener("pointermove"',
        'addEventListener("pointerup"',
        'addEventListener("pointercancel"',
        'addEventListener("wheel"',
        'addEventListener("keydown"',
        'event.key === "ArrowUp"',
        'event.key === "ArrowDown"',
        'event.key === "ArrowLeft"',
        'event.key === "ArrowRight"',
        'event.key === "+"',
        'event.key === "-"',
        'event.key === "0"',
        'event.key.toLowerCase() === "p"',
        'event.key.toLowerCase() === "b"',
        'event.key === "Escape"',
    ):
        assert marker in html

    for viewport_id in (
        "overview-map",
        "lbs-map",
        "permission-map",
        "pace-fit-map",
        "architecture-map",
        "navigation-training-map",
        "navigation-workspace-map",
    ):
        assert (
            f'renderDashboardMapViewport("{viewport_id}"' in html
            or f'id: "{viewport_id}"' in html
        )

    assert "mapViewportById: {}" in html
    assert 'role="region"' in html
    assert 'tabindex="0"' in html
    assert "ArrowUp ArrowDown ArrowLeft ArrowRight + - 0 P B Escape" in html
    assert "ArrowUp ArrowDown ArrowLeft ArrowRight + - 0 P Escape" in html
    assert 'data-map-mouse-zoom="${mouseZoomEnabled ? "true" : "false"}"' in html
    assert 'data-map-wheel-zoom="${wheelZoomEnabled ? "true" : "false"}"' in html
    assert "data-dashboard-map-stage" in html
    assert "data-dashboard-map-selection" in html
    assert "Click or drag in any direction to zoom in" in html
    assert "drag up-left to zoom out" not in html


def test_embedded_map_surfaces_support_mouse_pan_and_matching_keyboard_tools() -> None:
    for page in (PRETRIP_PAGE, AFTER_ACTION_PAGE, DEBUG_PAGE):
        html = page.read_text(encoding="utf-8")

        for marker in (
            'id="panMode"',
            'aria-label="Mouse drag pan"',
            "function setMapInteractionMode(",
            "function beginMapPointerPan(",
            "function updateMapPointerPan(",
            "function finishMapPointerPan(",
            "function handleMapWheelZoom(",
            'addEventListener("wheel", handleMapWheelZoom',
            'event.key === "+"',
            'event.key === "-"',
            'event.key === "0"',
            'event.key.toLowerCase() === "p"',
            'event.key.toLowerCase() === "b"',
            'event.key === "Escape"',
        ):
            assert marker in html


def test_weather_embedded_map_keeps_the_basic_map_view_controls_visible() -> None:
    html = PAGE.read_text(encoding="utf-8")
    weather_embed_style = html.split(
        'style.id = "scout-dashboard-weather-map-style"', 1
    )[1].split("const childWindow", 1)[0]
    frame_state_rule = html.split(".weather-cwa-frame-state {", 1)[1].split("}", 1)[0]

    assert "#readinessStrip, .toolbar-title" in weather_embed_style
    assert ".toolbar { display:block !important;" in weather_embed_style
    assert '.control-group[aria-label="Map view controls"]' in weather_embed_style
    assert '.toolbar-row[aria-label="Map tools"]' in weather_embed_style
    assert ".toolbar .layer-menu" in weather_embed_style
    assert "#readinessStrip, .toolbar," not in weather_embed_style
    assert "top: 58px;" in frame_state_rule


def test_weather_embedded_map_defaults_to_rudy_tw_and_cwa_imagery_only() -> None:
    html = PAGE.read_text(encoding="utf-8")
    pretrip_html = PRETRIP_PAGE.read_text(encoding="utf-8")
    weather_layer_defaults = html.split(
        "const WEATHER_LAYER_DEFAULTS = Object.freeze(", 1
    )[1].split("const WEATHER_EMBEDDED_MAP_LAYER_IDS", 1)[0]
    weather_layer_contract = html.split(
        "const WEATHER_EMBEDDED_MAP_LAYER_IDS = Object.freeze([", 1
    )[1].split("]);", 1)[0]
    weather_frame_adapter = html.split(
        "function applyWeatherCwaMapFrame(frame, attempt = 0)", 1
    )[1].split("function bindWeatherCwaMapFrame(frame)", 1)[0]
    weather_section = html.split(
        '<iframe class="weather-cwa-map-frame"', 1
    )[1].split("</iframe>", 1)[0]
    map_viewport_adapter = pretrip_html.split(
        "function applyMapViewport()", 1
    )[1].split("function mapLayerRank(", 1)[0]
    pretrip_load = pretrip_html.split(
        "async function load()", 1
    )[1].split("load().catch", 1)[0]

    assert '"rudy-twmap"' in weather_layer_contract
    assert '"cwa-weather"' in weather_layer_contract
    assert '"cwa-qpf"' not in weather_layer_contract
    assert weather_layer_contract.count('"') == 4
    assert 'layerId === "cwa-weather"' in weather_layer_defaults
    assert "&mapOnly=1&wheelZoom=0&initialLayers=${encodeURIComponent(" in weather_section
    assert "WEATHER_EMBEDDED_MAP_LAYER_IDS.join" in weather_section
    assert "SCOUT_LAYER_IDS.forEach(layerId =>" in weather_frame_adapter
    assert (
        "WEATHER_EMBEDDED_MAP_LAYER_IDS.includes(layerId)"
        in weather_frame_adapter
    )
    assert (
        'layerId === "rudy-twmap" || state.layerEnabled[layerId] !== false'
        in weather_frame_adapter
    )
    assert 'get("initialLayers")' in pretrip_html
    assert "function applyInitialLayerSelection()" in pretrip_html
    assert pretrip_load.index("applyInitialLayerSelection();") < pretrip_load.index(
        "bindControls();"
    )
    assert (
        'if (layerInputChecked("terrain")) '
        "renderTerrainMetadata(terrainGroup, view, bounds);"
        in pretrip_html
    )
    assert 'sourceKind: "scout_proxy_tile"' in pretrip_html
    assert 'sourceId: "happyman_rudy_twmap"' in pretrip_html
    assert 'cacheLayerId: "rudy-twmap"' in pretrip_html
    assert "renderRasterBasemapLayers(state.view);" in map_viewport_adapter
    assert (
        '#mapRendererShell[data-map-renderer-active="maplibre"] #map '
        "{ display:none !important; }"
        in weather_frame_adapter
    )
    assert (
        '#mapRendererShell[data-map-renderer-active="svg"] #mapLibreEvidenceMap '
        "{ display:none !important; }"
        in weather_frame_adapter
    )


def test_weather_embedded_map_loads_cwa_imagery_only_after_layer_enable() -> None:
    html = PAGE.read_text(encoding="utf-8")
    pretrip_html = PRETRIP_PAGE.read_text(encoding="utf-8")
    imagery_gate = pretrip_html.split(
        "async function loadCwaWeatherImageryIfEnabled(projectId)", 1
    )[1].split("async function loadCwaRainfallGridOverlay(view)", 1)[0]
    project_reload = pretrip_html.split(
        "async function reloadProjectView()", 1
    )[1].split("async function loadOsmPbfVectorLayer(view)", 1)[0]
    layer_change_handler = pretrip_html.split(
        "function handleLayerChange(event)", 1
    )[1].split("function closeLayerMenus(", 1)[0]
    bridge_wait = html.split(
        "function weatherCwaBridgeShouldWait(snapshot = {})", 1
    )[1].split("function scheduleWeatherCwaBridgeRetry(", 1)[0]

    assert "if (!cwaWeatherLayerInput()?.checked)" in imagery_gate
    assert "return null;" in imagery_gate
    assert "await loadCwaWeatherImagery(projectId)" in imagery_gate
    assert (
        "const imageryPromise = loadCwaWeatherImageryIfEnabled(PROJECT_ID);"
        in project_reload
    )
    assert (
        "const imageryPromise = loadCwaWeatherImagery(PROJECT_ID)"
        not in project_reload
    )
    assert 'input.dataset.layer !== "cwa-weather"' in layer_change_handler
    assert "void loadCwaWeatherImageryIfEnabled(PROJECT_ID);" in layer_change_handler
    assert 'state.layerEnabled["cwa-weather"] === false' in bridge_wait
    assert "return false;" in bridge_wait


def test_weather_route_bbox_callout_is_collapsible_and_compact_by_default() -> None:
    html = PAGE.read_text(encoding="utf-8")
    state_init = html.split("const state = {", 1)[1].split("selectedAction:", 1)[0]
    callout_renderer = html.split(
        "function renderWeatherIntersectionMap(snapshot)", 1
    )[1].split("function renderWeatherActions(snapshot)", 1)[0]
    control_binding = html.split(
        "function bindWeatherCwaControls()", 1
    )[1].split("function bindRenderedControls()", 1)[0]
    callout_styles = html.split(".weather-map-route-callout {", 1)[1].split(
        ".weather-map-timeline {", 1
    )[0]

    assert "weatherIntersectionCalloutExpanded: false" in state_init
    assert '<details class="weather-map-route-callout"' in callout_renderer
    assert 'data-weather-intersection-callout-toggle="true"' in callout_renderer
    assert 'data-weather-intersection-callout-action="true"' in callout_renderer
    assert (
        '${state.weatherIntersectionCalloutExpanded ? "open" : ""}'
        in callout_renderer
    )
    assert "callout.compactTitle" in callout_renderer
    assert "state.weatherIntersectionCalloutExpanded = callout.open" in control_binding
    assert 'callout.addEventListener("toggle"' in control_binding
    assert ":not([open])" in callout_styles
    assert "text-overflow: ellipsis" in callout_styles


def test_scout_dashboard_map_route_removes_header_without_losing_mobile_navigation() -> None:
    html = PAGE.read_text(encoding="utf-8")

    header_rule = html.split(
        ".dashboard-shell.is-frame-full .topbar {", 1
    )[1].split("}", 1)[0]
    frame_rule = html.split(
        ".dashboard-shell.is-frame-full .dashboard-frame {", 1
    )[1].split("}", 1)[0]
    assert "display: none;" in header_rule
    assert "grid-template-rows: minmax(0, 1fr);" in frame_rule
    assert 'id="dashboardMapNavToggle"' in html
    assert html.count("data-dashboard-nav-toggle aria-controls") == 2
    assert 'document.querySelectorAll("[data-dashboard-nav-toggle]")' in html
    assert 'state.route === "map" ? "dashboardMapNavToggle"' in html


def test_mobile_navigation_route_keeps_visible_global_sidebar_opener() -> None:
    html = PAGE.read_text(encoding="utf-8")

    mobile_override = html.split(
        "/* qualification-mobile-navigation-global-opener */", 1
    )[1].split("@media (max-width: 760px)", 1)[0]

    assert ".dashboard-shell.is-page-header-hidden .topbar {" in mobile_override
    assert "display: flex;" in mobile_override
    assert "min-height: 56px;" in mobile_override
    assert (
        ".dashboard-shell.is-page-header-hidden .dashboard-frame {"
        in mobile_override
    )
    assert "grid-template-rows: auto minmax(0, 1fr);" in mobile_override
    assert ".dashboard-shell.is-page-header-hidden .topbar-title-row h2" in mobile_override
    assert ".dashboard-shell.is-page-header-hidden .status-strip" in mobile_override
    assert "display: none;" in mobile_override
    assert "width: 44px;" in html.split(".dashboard-nav-toggle {", 1)[1].split("}", 1)[0]


def test_weather_hydrology_layers_are_required_on_main_map_with_na_fallback() -> None:
    html = PAGE.read_text(encoding="utf-8")
    pretrip_html = PRETRIP_PAGE.read_text(encoding="utf-8")

    weather_layer_ids = (
        "soil-moisture",
        "antecedent-rain",
        "cwa-qpf",
        "cwa-weather",
        "weather-api",
    )
    weather_layer_contract = html.split(
        "const WEATHER_LAYER_IDS = Object.freeze([", 1
    )[1].split("]);", 1)[0]
    map_evidence_renderer = html.split(
        "function renderMapEvidenceRail()", 1
    )[1].split("function dashboardCwaDerivedStatus", 1)[0]
    map_frame_adapter = html.split(
        "function applyPretripMapOnlyFrame(frame)", 1
    )[1].split("function projectCounts()", 1)[0]
    weather_renderer = html.split(
        "function renderWeatherIntersectionMap(snapshot)", 1
    )[1].split("function renderWeatherActions(snapshot)", 1)[0]

    for layer_id in weather_layer_ids:
        assert f'"{layer_id}"' in weather_layer_contract

    assert (
        "const WEATHER_LAYER_DEFAULTS = Object.freeze(Object.fromEntries("
        in html
    )
    assert (
        'WEATHER_LAYER_IDS.map(layerId => [layerId, layerId === "cwa-weather"])'
        in html
    )
    assert "...WEATHER_LAYER_DEFAULTS" in html
    assert 'aria-label="Weather and hydrology layer controls"' in weather_renderer
    assert 'data-weather-layer-control="${escapeHtml(layer.id)}"' in weather_renderer
    assert "renderDashboardCwaImageryControls()" not in map_evidence_renderer
    assert "projectRequiredWeatherLayersInMapFrame(frame)" in map_frame_adapter
    assert "function setEmbeddedPretripLayerEnabled" in html
    assert "function syncWeatherLayerControls" in html
    assert "function projectRequiredWeatherLayersInMapFrame" in html
    assert 'data-dashboard-weather-layer-required' in html
    assert 'data-dashboard-weather-layer-availability' in html
    assert 'data-dashboard-weather-layer-state="true"' in html
    assert 'status.textContent = "NA"' in html
    assert "const availabilityReason = available" in html
    assert '"no_prepared_layer_evidence"' in html
    assert "MutationObserver" in map_frame_adapter
    assert "excludeWeatherLayersFromMapFrame" not in html
    assert 'data-dashboard-weather-layer-hidden="true"' not in html

    for marker in (
        'data-weather-cwa-product="true"',
        'data-weather-cwa-window="true"',
        'data-weather-cwa-timeline="true"',
        'data-weather-cwa-opacity="radar"',
        'data-weather-cwa-opacity="satellite"',
        'data-weather-cwa-rainfall-product="true"',
        'data-weather-cwa-rainfall-opacity="true"',
        'data-weather-cwa-rainfall-legend="true"',
        'data-weather-cwa-rainfall-status="true"',
        'data-weather-cwa-play="true"',
        'data-weather-cwa-status="true"',
        'aria-label="Weather CWA rainfall, radar and satellite controls"',
        "bindWeatherCwaMapFrame",
        "syncWeatherCwaBridgeState",
        "scoutCwaImageryController",
        'scout:cwa-imagery-state',
        "cache-only",
        "candidate-only",
    ):
        assert marker in html

    assert "window.scoutCwaImageryController" in pretrip_html
    assert "function cwaImageryStateSnapshot()" in pretrip_html
    assert 'new CustomEvent("scout:cwa-imagery-state"' in pretrip_html
    assert "/admin/pretrip/projects/${encodeURIComponent(projectId)}/weather-imagery" in pretrip_html
    assert "SCOUT_CWA_API_KEY" not in html


def test_scout_dashboard_cwa_imagery_documentation_contract() -> None:
    dashboard_doc = DOC.read_text(encoding="utf-8")
    layer_doc = LAYER_CONTRACT_DOC.read_text(encoding="utf-8")
    weather_doc = WEATHER_DOC.read_text(encoding="utf-8")

    assert "Six Axis Weather owns weather and hydrology controls" in dashboard_doc
    assert "same-origin pretrip controller" in dashboard_doc
    assert "cache-only" in dashboard_doc
    assert "Six Axis Weather" in layer_doc
    assert "scoutCwaImageryController" in layer_doc
    assert "Exploring for Six Axis → Weather" in weather_doc
    assert "server-side" in weather_doc


def test_scout_dashboard_debug_message_runtime_details_contract() -> None:
    html = PAGE.read_text(encoding="utf-8")

    for function_name in (
        "renderDebugRuntimeDetails",
        "renderDebugRuntimeSummary",
        "renderDebugActiveDetail",
        "renderDebugStateDetail",
        "renderDebugMonitorDetail",
        "renderDebugSoftwareDetail",
        "renderDebugHardwareDetail",
        "renderDebugIngressDetail",
        "renderDebugIncidentDetail",
        "renderDebugSkillToolDetail",
        "renderDebugOutboundDetail",
        "renderDebugBoundaryDetail",
        "renderDebugApiDetail",
        "renderDebugVisualPanel",
        "renderDebugHardwareInterfaceNode",
        "renderDebugBoundaryGateGrid",
        "renderDebugApiTile",
        "debugRuntimeMatrix",
        "activeDebugRuntimeRecord",
        "debugEventMatchesCategory",
        "bindDebugDetailControls",
        "debugEndpointText",
        "debugAllEvents",
        "debugProviderEntries",
    ):
        assert f"function {function_name}" in html

    for label in (
        "Runtime Details",
        "L0-L4",
        "Events",
        "Hardware",
        "Software",
        "Monitor",
        "Provider",
        "Ingress",
        "Incident",
        "Ln / Skill",
        "Skills",
        "Tools",
        "Outbound",
        "Boundary",
        "API",
        "Current L0-L4 State",
        "Monitoring Center",
        "Provider Degraded Status",
        "Runtime Software State",
        "Hardware Readiness",
        "Hardware Interface Bus",
        "Hardware Providers",
        "Hardware Boundary Gates",
        "Mobile/Wearable Ingress",
        "Ingress Boundary",
        "Incident And Bridge Status",
        "Ln And Skill Runs",
        "Agent Tool Trace",
        "Scout Skills",
        "Outbound Queue",
        "Boundary Snapshot",
        "API Payloads",
        "Runtime Sources",
        "Boundary Notes",
        "Debug Message Stream",
        "API Payload Matrix",
    ):
        assert label in html

    for source in (
        "/debug/events?limit=200",
        "/debug/state",
        "/debug/messages",
        "/debug/mobile-wearable/ingress",
        "/debug/monitoring",
        "/admin/hardware-readiness/context",
        "GPIO/I2C/I2S/TTS/Bluetooth/UART/power/GNSS/IMU/USB/SSD inventory",
    ):
        assert source in html

    assert "DEBUG_DETAIL_CATEGORIES" in html
    assert 'activeDebugDetail: "state"' in html
    for state_field in (
        "runtimeDebugEvents",
        "runtimeDebugEventPayload",
        "debugRuntimeState",
        "debugMessages",
        "debugMessagesPayload",
        "mobileWearableIngress",
        "monitoringCenter",
        "hardwareReadiness",
    ):
        assert state_field in html

    assert 'data-debug-runtime-details="true"' in html
    assert 'data-debug-message-details="true"' in html
    assert 'data-debug-message-sources="true"' in html
    assert 'data-debug-console="true"' in html
    assert 'data-debug-stream-tables="true"' in html
    assert 'data-debug-detail="${escapeHtml(record.id)}"' in html
    assert "debug-telemetry-bar" in html
    assert "debug-tab-shell" in html
    assert "debug-console-grid" in html
    assert "debug-drawer-stack" in html
    assert "debug-table-grid" in html
    assert "debug-slim-row" in html
    assert "debug-node-grid" in html
    assert "debug-flow" in html
    assert "debug-bus" in html
    assert "debug-level-strip" in html
    assert "debug-api-tile" in html
    assert "debug-pin-grid" in html
    assert "/admin/debug" in html
    assert "/admin/hardware-readiness/context" in html
    assert "debug-projection-events" in html
    assert "debug-projection" in html
    assert "not triggered from dashboard" in html
    assert "readiness metadata only" in html
    assert "mock / dry-run message evidence only" in html
    assert "state.activeDebugDetail = button.dataset.debugDetail || \"state\";" in html


def test_scout_dashboard_outdoor_six_forces_subtree_contract() -> None:
    html = PAGE.read_text(encoding="utf-8")

    for route, label, system_name in (
        ("outdoor-route-context", "Route Context", "Route Context Intelligence"),
        ("outdoor-pace-fit", "Pace Fit", "Pace Fit"),
        ("outdoor-permission", "Permission", "Contextual Permissioning"),
        ("outdoor-architecture", "Architecture", "Route Architecture Intelligence"),
        ("outdoor-weather", "Weather", "Weather-to-Decision Intelligence"),
        ("outdoor-navigation", "Navigation", "Navigation & Terrain Intelligence"),
    ):
        assert f'data-route="{route}"' in html
        assert label in html
        assert system_name in html

    for removed_label in ("戶外六力", "探索力", "自信力", "勇氣力", "路線力", "天氣力", "地圖力"):
        assert removed_label not in html

    for decision in (
        "GO",
        "CONDITIONAL_GO",
        "GUIDED_ONLY",
        "CHANGE_PLAN",
        "DELAY",
        "NO_GO",
        "ESCALATE",
    ):
        assert decision in html


def test_navigation_ordered_clues_describes_named_point_route_positions() -> None:
    html = PAGE.read_text(encoding="utf-8")
    renderer = html.split("function renderNavigationOrderedClues", 1)[1].split(
        "function renderNavigationTopology", 1
    )[0]

    assert 'ledger.ordered_clue_chain_kind === "named_point_route_positions"' in renderer
    assert "依 Golden Route 路程排序的命名地點線索" in renderer
    assert "僅供閱讀，不代表已確認歷史路線" in renderer


def test_scout_dashboard_navigation_terrain_intelligence_workbench_contract() -> None:
    html = PAGE.read_text(encoding="utf-8")
    navigation = html.split("function renderNavigationPage", 1)[1].split(
        "function architectureSnapshot", 1
    )[0]

    for marker in (
        'data-navigation-terrain-intelligence="true"',
        'data-terrain-contour-map="true"',
        'data-terrain-feature-detail="true"',
        'data-navigation-boundary="candidate-only"',
        "function navigationTerrainFeatures()",
        "function renderNavigationTerrainMap(",
        "function renderNavigationTerrainDetail(",
        "function bindNavigationTerrainControls()",
        "bindNavigationTerrainControls();",
        "navigationSelectedFeatureId",
        "navigationSelectedLivePointId",
        "navigationSelectedPressurePointId",
        "navigationSelectedStructurePointId",
        "navigationSelectedTerrainEventId",
        "navigationTerrainLens",
        "navigationTerrainSourceMode",
        "navigationTerrainViewMode",
        "navigationTerrainEvidenceDomain",
        "navigationTerrainVerticalExaggeration",
        "navigationSelectedHierarchyEdgeId",
            "navigationTerrainData",
            "terrain_validation",
        "loadNavigationTerrainData",
        "function renderNavigationWorkspaceMap(",
        "function renderNavigationTerrainMesh(",
        "function renderNavigationTerrainMapLibreHost(",
        "function navigationTerrainMapLibreFeatureCollection(",
        "function navigationTerrainMapLibreStyle(",
        "async function initializeNavigationTerrainMapLibre(",
        "function destroyNavigationTerrainMapLibre(",
        "function renderNavigationTerrainReviewWorkbench(",
        "function renderNavigationTerrainEvidenceInspector(",
        "function renderNavigationTerrainTopDownLayer(",
        "function renderNavigationFeatureExtraction(",
        "function renderNavigationSourceLedger(",
        "function renderNavigationOrderedClues(",
        "function renderNavigationTopology(",
        "function renderNavigationPassagePrior(",
        "function renderNavigationEvidenceGaps(",
        "function renderNavigationEvidenceWorkbench(",
        "function navigationTerrainHierarchyPath(",
        "function navigationTerrainUncertaintyBandStrokeWidth(",
        "function renderNavigationTerrainEventTimeline(",
        "function renderNavigationTerrainEventDetail(",
        "function navigationTerrainSelectionModel(",
        "function renderNavigationCandidateNavigator(",
        "function setNavigationTerrainSelection(",
        'data-navigation-workspace-map="true"',
        'data-navigation-terrain-review-workbench="true"',
        'data-navigation-terrain-view="',
        'data-navigation-terrain-vertical-exaggeration="',
        'data-navigation-terrain-evidence-domain="',
        'data-navigation-candidate-only-strip="true"',
        'data-navigation-terrain-evidence-inspector="true"',
        'data-navigation-terrain-3d="true"',
        'data-navigation-maplibre-map="',
        'data-navigation-maplibre-fit="',
        'data-navigation-maplibre-state="',
        'data-navigation-structure-point-id="',
        'data-navigation-structure-kind="',
        'data-navigation-route-path="true"',
        'data-navigation-terrain-edge-kind="',
        'data-navigation-terrain-band="true"',
        'data-navigation-terrain-event-id="',
            'data-navigation-terrain-event-timeline="true"',
            'data-navigation-terrain-validation="',
        'data-navigation-source-ledger="true"',
        'data-navigation-ordered-clues="true"',
        'data-navigation-route-topology="true"',
        'data-navigation-terrain-passage-prior="true"',
        'data-navigation-historical-option="',
        'data-navigation-evidence-gaps="true"',
        "Workspace DEM + candidate morphology",
        "2D Evidence",
        "3D Local Detail",
        "Split View",
        "Golden Route 地形脈絡",
        "不增加 DEM 原始解析度",
        "Observed Passage Pattern Prior",
        "Unknown ≠ negative",
        "Terrain Evidence Only",
        "Reveal Observed Context",
        "Reveal Learned Prior",
        "CANDIDATE-ONLY · RUNTIME SAFETY TRUTH = FALSE · OPERATIONAL = FALSE",
        "MAPLIBRE 3D TERRAIN",
        "MAPLIBRE 2D EVIDENCE",
        "MAP MARKER",
        "SOURCE SUPPORT / RENDER AUDIT",
        "External-context overlap: non-causal",
        "no external basemap loaded",
        "Prepared DTM + GPX source ledger",
        "候選支持區",
        "Shadow 關係說明",
        "不需要逐筆審核",
        "/navigation-terrain-intelligence",
        "Workspace terrain projection is preparing.",
        "scheduleNavigationTerrainPolling",
        "stopNavigationTerrainPolling",
        "navigationTerrainPollTimer",
        'snapshot.status === "preparing"',
    ):
        assert marker in html

    assert "走錯徵兆" not in navigation
    assert "回復檢查" not in navigation
    assert "formatDistanceKm(event.route_distance_m)" not in navigation
    assert "navigation-terrain-hierarchy-edge" not in navigation
    assert "function renderNavigationReviewQueue(" not in html
    assert "data-navigation-review-decision" not in html
    assert "UNSAVED LOCAL DRAFT" not in html
    assert "navigation-terrain-hierarchy-band" in html
    assert "--navigation-route: #d1005d;" in html
    assert "--navigation-ridge: #ef5b0c;" in html
    assert "--navigation-drainage: #006eb8;" in html
    assert "--navigation-tributary: #008f9c;" in html
    assert "--navigation-event: #d72f20;" in html
    assert '[data-navigation-legend-kind="tributary"]' in html
    assert "navigation-workspace-route-halo" in html
    assert '"/admin/vendor/maplibre-gl/6.2.0/maplibre-gl.mjs"' in html
    assert 'href="/admin/vendor/maplibre-gl/6.2.0/maplibre-gl.css"' in html
    assert "unpkg.com/maplibre-gl" not in html
    assert 'type: "raster-dem"' in html
    assert 'encoding: "mapbox"' in html
    assert 'scrollZoom: false' in html
    assert 'doubleClickZoom: false' in html
    assert 'boxZoom: true' in html
    assert 'dragPan: true' in html
    assert 'keyboard: true' in html
    assert 'source: "scout-terrain-dem"' in html
    assert 'source: "scout-terrain-hillshade-dem"' in html
    assert 'source: "scout-terrain-candidates"' in html
    assert 'function navigationTerrainRudyOpacity(mode)' in html
    assert 'return mode === "3d" ? .46 : .74;' in html
    assert '"raster-opacity": navigationTerrainRudyOpacity(mode)' in html
    assert '"raster-fade-duration": 0' in html
    assert '"raster-contrast": mode === "3d" ? .24 : 0' in html
    assert '"raster-saturation": mode === "3d" ? -.14 : 0' in html
    assert '...(revealObservedContext ? [rudyLayer] : []),\n        ...terrainRasterLayers' in html
    assert 'mode === "3d" ? "terrain" : "flat"' in html
    assert 'data-navigation-rudy-opacity="${navigationTerrainRudyOpacity(mode)}"' in html
    assert 'function navigationTerrainCameraMinimumZoom(dem, mode)' in html
    assert 'mode === "3d" ? Math.min(22, sourceZoom + 1)' in html
    assert ': Math.max(5, sourceZoom - 5);' in html
    assert 'data-navigation-terrain-camera-min-zoom="${navigationTerrainCameraMinimumZoom(dem, mode)}"' in html
    assert 'data-navigation-terrain-source-min-zoom="${valueOrDash(dem.minzoom)}"' in html
    assert 'const terrainZoomFloor = navigationTerrainMapLibreRuntime.maps.reduce(' not in html
    assert 'FULL GOLDEN ROUTE · independent 2D scale' in html
    assert 'data-dashboard-map-screen-stroke="7"' in html
    assert 'data-dashboard-map-screen-stroke="4.5"' in html
    assert 'data-navigation-structure-label-visibility="selected-only"' in html
    assert 'point.id === selectedStructurePoint?.id ? "8" : "4"' in html
    assert 'data-navigation-terrain-event-label-visibility="selected-only"' in html
    assert 'location.id === selectedEventLocation?.id ? "8" : "4"' in html
    assert "overflow-wrap: anywhere;" in html
    assert 'class="navigation-live-metrics is-boundary"' in html

    for legend_label in (
        "洋紅路線",
        "橘色稜脊",
        "深藍主谷",
        "藍綠支谷",
        "紅色位置群",
    ):
        assert legend_label in navigation

    assert "DEM 集水骨幹推估" in navigation
    assert "DEM 連通谷地推估 · 非現地地形確認" in navigation

    for lens, label in (
        ("structure", "地形結構"),
        ("pressure", "坡度壓力"),
        ("risk", "風險地形"),
        ("retreat", "撤退方向"),
        ("events", "Shadow 事件"),
    ):
        assert f'["{lens}", "{label}"]' in navigation
    for feature in (
        "ridge",
        "valley",
        "saddle",
        "fork",
        "cliff",
        "gully",
        "steep-slope",
        "exposure",
    ):
        assert f'type: "{feature}"' in html

    for label in (
        "稜線",
        "谷線",
        "鞍部",
        "岔路",
        "崩壁",
        "溪谷",
        "陡坡",
        "曝露地形",
        "撤退方向",
        "等高線判讀",
    ):
        assert label in html

    assert "safe route" not in navigation.lower()
    assert "不能單獨證明步道存在" in navigation
    assert "不要求使用者逐筆驗真或修正等高線" in navigation
    assert "點選只用於查看計算來源" in html
    assert 'role="listitem"\n                class="navigation-event-card"' not in navigation
    assert "void loadConnectedPreparationStatus();" in html
    assert 'triggerDashboardConnectedPreparation("dashboard-open")' not in html
    assert 'const pageHeaderHidden = route === "outdoor-navigation";' in html
    assert (
        'dashboardShell?.classList.toggle("is-page-header-hidden", pageHeaderHidden);'
        in html
    )
    assert ".dashboard-shell.is-page-header-hidden .topbar {" in html
    assert ".dashboard-shell.is-page-header-hidden .dashboard-frame {" in html
    assert 'class="navigation-terrain-brief"' not in navigation
    assert "data-navigation-terrain-source=" not in navigation
    assert "${renderNavigationReadingChecklist()}" not in navigation
    assert "Map Literacy Checklist" not in navigation
    assert 'class="navigation-terrain-primary"' in navigation
    assert ".navigation-terrain-primary {" in html
    assert (
        navigation.count(
            "renderNavigationTerrainEventTimeline(snapshot, selectedTerrainEvent)"
        )
        == 1
    )
    assert navigation.index(
        "renderNavigationTerrainEventTimeline(snapshot, selectedTerrainEvent)"
    ) < navigation.index('class="navigation-terrain-side"')
    assert "Workspace Terrain Evidence" not in navigation
    assert "讀懂地形，才知道方向何時開始消失。" not in navigation
    assert "Training fixture" not in navigation
    assert "not_prepared" in html
    assert "尚未由目前 terrain pipeline 抽取" in html
    assert "P0、P1、P2 不合併成一個安全分數" in html
    assert "reference GPX 不自動升格成替代路線" in html


def test_navigation_maplibre_composes_shared_2d_and_3d_terrain_layers() -> None:
    html = PAGE.read_text(encoding="utf-8")
    style = html.split(
        "function navigationTerrainMapLibreStyle", 1
    )[1].split("function navigationTerrainMapLibreCameraScope", 1)[0]

    for helper in (
        "function navigationTerrainRasterOverlay(",
        "function navigationTerrainRasterImageSource(",
        "function navigationTerrainLayerVisibility(",
        "function navigationTerrainMapLayerIds(",
        "function setNavigationTerrainMapLayerVisibility(",
    ):
        assert helper in html

    for source_id in (
        "scout-terrain-elevation-tint",
        "scout-terrain-contours",
        "scout-terrain-slope-shading",
    ):
        assert source_id in style

    assert 'type: "image"' in style
    assert 'type: "raster"' in style
    assert 'type: "hillshade"' in style
    assert 'const terrainRasterLayers = [' in style
    assert style.index("rudyLayer") < style.index("...terrainRasterLayers")
    assert style.index('id: "scout-terrain-elevation-tint"') < style.index(
        'id: "scout-terrain-contours"'
    )
    assert '"raster-resampling": "linear"' in style
    assert style.count('"raster-resampling": "linear"') >= 3
    assert 'navigationTerrainLayerVisible("elevation")' in style
    assert 'navigationTerrainLayerVisible("hillshade")' in style
    assert 'navigationTerrainLayerVisible("contours")' in style
    assert 'navigationTerrainLayerVisible("slope")' in style
    assert 'navigationTerrainLayerVisible("basemap")' in style
    assert 'navigationTerrainLayerVisible("route")' in style
    assert 'navigationTerrainLayerVisible("candidates")' in style
    assert 'terrain: {' in style
    assert 'source: "scout-terrain-dem"' in style


def test_navigation_map_layer_controls_do_not_recreate_or_refit_maps() -> None:
    html = PAGE.read_text(encoding="utf-8")
    setter = html.split(
        "function setNavigationTerrainMapLayerVisibility", 1
    )[1].split("function navigationTerrainMapLibreEventFeatureCollection", 1)[0]
    binder = html.split(
        "function bindNavigationTerrainControls", 1
    )[1].split("function bindSettingsControls", 1)[0]

    assert 'navigationTerrainLayerVisibility: {' in html
    assert 'navigationTerrainInspectorExpanded: false' in html
    assert 'data-navigation-terrain-layer-toggle="' in html
    assert 'data-navigation-terrain-inspector-toggle="true"' in html
    assert 'data-navigation-inspector-expanded="${String(inspectorExpanded)}"' in html
    assert 'hidden="${inspectorExpanded ? "" : "hidden"}"' not in html
    assert '${inspectorExpanded ? "" : "hidden"}' in html
    assert 'map.setLayoutProperty(layerId, "visibility", visibility);' in setter
    assert "navigationTerrainMapLibreStyle" not in setter
    assert "fitNavigationTerrainMapLibre" not in setter
    assert "render()" not in setter
    assert 'button.setAttribute("aria-pressed", String(visible));' in setter
    assert 'state.navigationTerrainLayerVisibility = {' in setter
    assert 'shell.querySelectorAll("button[data-navigation-terrain-layer-toggle]")' in binder
    assert 'setNavigationTerrainMapLayerVisibility(layerKey, !current);' in binder


def test_navigation_2d_and_3d_sync_center_without_cross_mode_zoom_reset() -> None:
    html = PAGE.read_text(encoding="utf-8")
    synchronizer = html.split(
        "function synchronizeNavigationTerrainMapLibre", 1
    )[1].split("function navigationTerrainSelectionFocusTarget", 1)[0]

    assert "const center = sourceEntry.map.getCenter();" in synchronizer
    assert "const zoom = sourceEntry.map.getZoom();" in synchronizer
    assert "const synchronizeZoom = entry.mode === sourceEntry.mode;" in synchronizer
    assert "entry.map.jumpTo({center, ...(synchronizeZoom ? {zoom} : {})});" in synchronizer
    assert "fitNavigationTerrainMapLibre" not in synchronizer


def test_navigation_page_is_a_map_first_reference_workspace() -> None:
    html = PAGE.read_text(encoding="utf-8")
    navigation = html.split("function renderNavigationPage", 1)[1].split(
        "function architectureSnapshot", 1
    )[0]

    assert 'navigationTerrainViewMode: "map"' in html
    assert 'data-navigation-command-center="true"' in navigation
    assert 'data-navigation-primary-stage="true"' in navigation
    assert 'data-navigation-context-inspector="true"' in navigation
    assert 'data-navigation-utility-drawer="qgis"' in navigation
    assert 'data-navigation-utility-drawer="qgis-run-receipt"' in navigation
    assert 'data-navigation-utility-drawer="artifact-metadata"' in navigation
    assert 'data-navigation-supporting-evidence="true"' in navigation
    assert 'data-navigation-map-legend="true"' in navigation
    assert 'class="route-tabs ${activeRoute === "outdoor-navigation" ? "is-navigation-active" : ""}"' in html
    assert "routeTabs.scrollLeft = Math.max" in html

    command_center = navigation.split(
        'data-navigation-command-center="true"', 1
    )[1].split('data-navigation-primary-stage="true"', 1)[0]
    context_inspector = navigation.split(
        'data-navigation-context-inspector="true"', 1
    )[1].split('data-navigation-supporting-evidence="true"', 1)[0]
    assert 'class="navigation-terrain-lenses"' in command_center
    assert context_inspector.index("renderNavigationWorkspaceDetail") < (
        context_inspector.index("renderQgisAnalysisPanel")
    )
    assert context_inspector.index("renderNavigationCandidateNavigator") < (
        context_inspector.index("renderNavigationWorkspaceDetail")
    )
    assert context_inspector.index("renderNavigationCandidateNavigator") < (
        context_inspector.index("renderQgisAnalysisPanel")
    )
    assert '<details class="navigation-utility-drawer"' in context_inspector
    assert '<details class="navigation-supporting-evidence"' in navigation
    assert "Map Literacy Checklist" not in navigation


def test_navigation_terrain_derivatives_do_not_create_a_human_map_correction_queue() -> None:
    html = PAGE.read_text(encoding="utf-8")
    navigation = html.split("function renderNavigationPage", 1)[1].split(
        "function architectureSnapshot", 1
    )[0]
    terrain_detail = html.split("function renderNavigationWorkspaceDetail", 1)[1].split(
        "function renderNavigationTerrainEventTimeline", 1
    )[0]
    qgis_panel = html.split("function renderQgisAnalysisPanel", 1)[1].split(
        "function renderQgisArtifactMetadata", 1
    )[0]

    assert "自動衍生圖層只協助閱讀 Golden Route 周邊的地形脈絡" in navigation
    assert "不是待辦清單" in navigation
    assert "不要求登山者驗真" in terrain_detail
    assert "data-qgis-review-evidence" not in html
    assert "function reviewQgisSpatialEvidence" not in html
    for misleading_review_text in (
        "Record Evidence Review",
        "Evidence review pending",
        "QGIS visual review",
        "comparison pending",
        "下一個證據",
        "人工複核地形候選",
        "審核清單",
    ):
        assert misleading_review_text not in navigation + terrain_detail + qgis_panel


def test_navigation_maplibre_uses_the_canvas_as_its_single_keyboard_surface() -> None:
    html = PAGE.read_text(encoding="utf-8")
    keyboard_surface = html.split(
        "function configureNavigationTerrainMapLibreKeyboardSurface", 1
    )[1].split("function fitNavigationTerrainMapLibre", 1)[0]
    initializer = html.split(
        "async function initializeNavigationTerrainMapLibre()", 1
    )[1].split("function navigationTerrainSelectedHierarchyEdge", 1)[0]
    assert 'const canvas = map.getCanvas();' in keyboard_surface
    assert 'host.removeAttribute("tabindex");' in keyboard_surface
    assert 'host.removeAttribute("role");' in keyboard_surface
    assert 'host.removeAttribute("aria-keyshortcuts");' in keyboard_surface
    assert 'canvas.setAttribute("role", "application");' in keyboard_surface
    assert 'canvas.setAttribute("aria-label", label);' in keyboard_surface
    assert 'canvas.setAttribute("aria-keyshortcuts", shortcuts);' in keyboard_surface
    assert 'canvas.dataset.navigationMaplibreKeyboardSurface = mode;' in keyboard_surface
    assert (
        "const keyboardSurface = configureNavigationTerrainMapLibreKeyboardSurface("
        in initializer
    )
    assert "keyboardSurface.focus({preventScroll: true});" in initializer
    assert "host.focus({preventScroll: true});" not in initializer


def test_navigation_terrain_event_locations_are_shared_by_map_and_evidence() -> None:
    html = PAGE.read_text(encoding="utf-8")
    location_helpers = html.split(
        "function navigationTerrainEventLocations", 1
    )[1].split("function navigationTerrainHierarchyPath", 1)[0]
    feature_collection = html.split(
        "function navigationTerrainMapLibreEventFeatureCollection", 1
    )[1].split("function navigationTerrainMapLibreBounds", 1)[0]
    timeline = html.split(
        "function renderNavigationTerrainEventTimeline", 1
    )[1].split("function renderNavigationSourceLedger", 1)[0]
    initializer = html.split(
        "async function initializeNavigationTerrainMapLibre()", 1
    )[1].split("function navigationTerrainSelectedHierarchyEdge", 1)[0]
    event_layers = html.split(
        'id: "scout-terrain-event-clusters"', 1
    )[1].split('id: "scout-terrain-event-location-label"', 1)[0]

    assert "const NAVIGATION_TERRAIN_EVENT_LOCATION_CLUSTER_M = 30;" in html
    assert "navigationTerrainEventLocations(snapshot)" in feature_collection
    assert 'kind: "terrain_event_location"' in feature_collection
    assert '"scout-terrain-event-locations"' in html
    assert 'cluster: true' in html
    assert 'id: "scout-terrain-event-clusters"' in html
    assert 'id: "scout-terrain-event-cluster-count"' in html
    assert 'id: "scout-terrain-events"' in html
    assert '"circle-radius": [\n              "interpolate"' in event_layers
    assert '["zoom"]' in event_layers
    assert '["case", ["==", ["get", "selected"], true], 9, 5]' in event_layers
    assert "navigationTerrainEventLocations(snapshot)" in timeline
    assert 'data-navigation-terrain-location-id="' in timeline
    assert "個地圖位置" in timeline
    assert "條已載入關係" in timeline
    assert "條未投影" in timeline
    assert "eventProjection.rendered_count || events.length" not in timeline
    assert "navigationTerrainEventLocationForEvent" in location_helpers
    assert "focusNavigationTerrainEventLocation" in html
    assert '"scout-terrain-event-clusters"' in initializer
    assert '"scout-terrain-events"' in initializer
    assert "getClusterExpansionZoom" in initializer
    assert "state.navigationSelectedTerrainEventId = eventId;" in initializer
    assert (
        'evidenceDomain === "observed" && lens === "events" '
        '? renderNavigationTerrainEventTimeline(snapshot, selectedTerrainEvent)'
        in html
    )


def test_navigation_maplibre_maps_do_not_show_pointer_following_hints() -> None:
    html = PAGE.read_text(encoding="utf-8")
    maplibre_host = html.split(
        "function renderNavigationTerrainMapLibreHost", 1
    )[1].split("function renderNavigationTerrainReviewWorkbench", 1)[0]
    workbench = html.split(
        "function renderNavigationTerrainReviewWorkbench", 1
    )[1].split("function navigationTerrainMapLibreCoordinates", 1)[0]

    assert "data-dashboard-map-hint-title" not in maplibre_host
    assert "data-dashboard-map-hint-summary" not in maplibre_host
    assert "data-dashboard-map-hint-source" not in maplibre_host
    assert 'class="navigation-terrain-review-status"' in workbench
    assert 'data-navigation-terrain-header-status="dem"' in workbench
    assert 'data-navigation-terrain-header-status="coverage"' in workbench
    assert 'data-navigation-terrain-header-status="scope"' in workbench


def test_navigation_maplibre_controls_do_not_trigger_a_lens_rerender() -> None:
    html = PAGE.read_text(encoding="utf-8")
    controls = html.split("function bindNavigationTerrainControls()", 1)[1].split(
        "function renderOutdoorPage", 1
    )[0]

    assert 'shell.querySelectorAll("button[data-navigation-terrain-lens]")' in controls
    assert 'shell.querySelectorAll("[data-navigation-terrain-lens]")' not in controls
    assert 'root.querySelectorAll("button[data-navigation-terrain-lens]")' in html
    assert 'rerenderNavigation(`button[data-navigation-terrain-lens="${cssEscape(state.navigationTerrainLens)}"]`)' in controls
    assert 'data-navigation-terrain-lens="${escapeHtml(lens)}"' in html


def test_navigation_maplibre_preserves_independent_cameras_across_rerenders() -> None:
    html = PAGE.read_text(encoding="utf-8")
    helpers = (
        "function navigationTerrainMapLibreCameraScope"
        + html.split("function navigationTerrainMapLibreCameraScope", 1)[1].split(
            "function destroyNavigationTerrainMapLibre", 1
        )[0]
    )
    lifecycle = html.split("function destroyNavigationTerrainMapLibre", 1)[1].split(
        "function navigationTerrainSelectedHierarchyEdge", 1
    )[0]

    for marker in (
        "cameraByMode: {}",
        "function navigationTerrainMapLibreCameraScope",
        "function navigationTerrainMapLibreCameraSnapshot",
        "function navigationTerrainMapLibreStoredCamera",
        "function rememberNavigationTerrainMapLibreCamera",
        "rememberNavigationTerrainMapLibreCamera(entry);",
        "const storedCamera = navigationTerrainMapLibreStoredCamera(snapshot, mode);",
        "if (!storedCamera) fitNavigationTerrainMapLibre(map, snapshot, mode);",
    ):
        assert marker in html

    node_program = "\n".join(
        (
            "const navigationTerrainMapLibreRuntime = {cameraByMode: {}};",
            'const projectId = () => "project-a";',
            helpers,
            """
const snapshotA = {
  project_id: "project-a",
  projection_compilation: {input_fingerprint: "route-a"},
  terrain_raster_dem: {source_fingerprint: "dem-a"},
};
const snapshotB = {
  project_id: "project-a",
  projection_compilation: {input_fingerprint: "route-b"},
  terrain_raster_dem: {source_fingerprint: "dem-a"},
};
const map = camera => ({
  getCenter: () => ({lng: camera.center[0], lat: camera.center[1]}),
  getZoom: () => camera.zoom,
  getPitch: () => camera.pitch,
  getBearing: () => camera.bearing,
});
const scopeKey = navigationTerrainMapLibreCameraScope(snapshotA);
rememberNavigationTerrainMapLibreCamera({
  mode: "2d",
  map: map({center: [121.25, 24.05], zoom: 13.75, pitch: 0, bearing: 0}),
  scopeKey,
});
rememberNavigationTerrainMapLibreCamera({
  mode: "3d",
  map: map({center: [121.27, 24.07], zoom: 17, pitch: 58, bearing: -28}),
  scopeKey,
});
process.stdout.write(JSON.stringify({
  twoD: navigationTerrainMapLibreStoredCamera(snapshotA, "2d"),
  threeD: navigationTerrainMapLibreStoredCamera(snapshotA, "3d"),
  changedProjection: navigationTerrainMapLibreStoredCamera(snapshotB, "2d"),
  modes: Object.keys(navigationTerrainMapLibreRuntime.cameraByMode).sort(),
}));
""",
        )
    )
    result = subprocess.run(
        ["node"],
        input=node_program,
        text=True,
        capture_output=True,
        check=True,
    )
    payload = json.loads(result.stdout)

    assert payload["twoD"]["zoom"] == 13.75
    assert payload["threeD"]["zoom"] == 17
    assert payload["twoD"]["center"] == [121.27, 24.07]
    assert payload["threeD"]["center"] == [121.27, 24.07]
    assert payload["twoD"]["pitch"] == 0
    assert payload["threeD"]["pitch"] == 58
    assert payload["changedProjection"] is None
    assert payload["modes"] == ["2d", "3d"]
    assert lifecycle.index("rememberNavigationTerrainMapLibreCamera(entry);") < lifecycle.index(
        "entry.map.remove();"
    )


def test_navigation_maplibre_fit_uses_full_golden_route_without_dem_zoom_lock() -> None:
    html = PAGE.read_text(encoding="utf-8")
    bounds_helpers = html.split(
        "function navigationTerrainGoldenRouteBounds", 1
    )[1].split("function navigationTerrainRudyTileTemplate", 1)[0]
    fit_and_sync = html.split(
        "function fitNavigationTerrainMapLibre", 1
    )[1].split("async function initializeNavigationTerrainMapLibre", 1)[0]
    initializer = html.split(
        "async function initializeNavigationTerrainMapLibre()", 1
    )[1].split("function navigationTerrainSelectedHierarchyEdge", 1)[0]

    assert "snapshot?.route_samples?.points" in bounds_helpers
    assert "navigationTerrainGoldenRouteBounds(snapshot)" in bounds_helpers
    assert "navigationTerrainMapLibreBounds(snapshot?.terrain_raster_dem || {})" in bounds_helpers
    assert 'const bounds = mode === "3d"' in fit_and_sync
    assert "navigationTerrainFitBounds(snapshot);" in fit_and_sync
    assert "map.getZoom() < minimumCameraZoom" in fit_and_sync
    assert "terrainZoomFloor" not in fit_and_sync
    assert "const zoom = sourceEntry.map.getZoom();" in fit_and_sync
    assert "const synchronizeZoom = entry.mode === sourceEntry.mode;" in fit_and_sync
    assert "...(synchronizeZoom ? {zoom} : {})" in fit_and_sync
    assert "fitNavigationTerrainMapLibre(map, snapshot, mode);" in initializer
    assert "minZoom: navigationTerrainCameraMinimumZoom(dem, mode)" in initializer
    assert 'isTerrain ? "prepared-dem-local-detail" : "golden-route"' in html
    assert 'isTerrain ? "Reset prepared DEM local detail" : "Fit entire Golden Route"' in html
    assert "3D LOCAL DETAIL" in html
    assert "中心同步 / 尺度獨立" in html
    assert "PARTIAL DEM COVERAGE" in html
    assert "map.queryTerrainElevation(cameraCenter)" in initializer
    assert "host.dataset.navigationTerrainElevationStatus" in initializer
    assert "DEM DECODED" in initializer
    assert "MAPLIBRE 3D TERRAIN · DEGRADED" in initializer
    assert "navigationTerrainVerticalExaggeration: 1," in html
    assert "bilinear display smoothing" in html
    assert "adds source resolution: no" in html


def test_navigation_uses_vector_map_when_terrain_rgb_is_not_prepared() -> None:
    html = PAGE.read_text(encoding="utf-8")
    workbench = html.split(
        "function renderNavigationTerrainReviewWorkbench", 1
    )[1].split("function navigationTerrainMapLibreFeatureCollection", 1)[0]

    assert "const terrainDemReady = navigationTerrainDemReady(snapshot);" in workbench
    assert '? renderNavigationTerrainMapLibreHost(snapshot, "2d")' in workbench
    assert ": renderNavigationWorkspaceMap(" in workbench
    assert "2D 向量證據 · Rudy+TW · Terrain RGB 未準備" in workbench


def test_navigation_partial_states_preserve_truthful_map_control_shell() -> None:
    html = PAGE.read_text(encoding="utf-8")
    loading_renderer = html.split(
        "function renderNavigationWorkspaceLoading(snapshot)", 1
    )[1].split("function renderNavigationPage(force)", 1)[0]

    assert 'renderDashboardMapViewport("navigation-workspace-map"' in loading_renderer
    assert 'data-navigation-workspace-map="${stateLabel}"' in loading_renderer
    assert 'data-dashboard-basemap-policy="rudy-twmap-only"' in loading_renderer
    assert 'data-navigation-evidence-state="${stateLabel}"' in loading_renderer
    assert "snapshot?.orientation_basemap?.bounds_wgs84" in loading_renderer
    assert "snapshot?.orientation_basemap?.status === \"ready\"" in loading_renderer
    assert "renderNavigationRudyTileLayer(displayBounds, baseZoom)" in loading_renderer
    assert 'data-navigation-basemap-layer="${hasBasemap ? "rudy-twmap" : "none"}"' in loading_renderer
    assert "Rudy+TW orientation basemap only" in loading_renderer
    assert "No terrain vectors or terrain tiles are claimed" in loading_renderer
    assert "No terrain projection has been prepared" in loading_renderer


def test_navigation_workspace_map_uses_dynamic_rudy_tw_tiles_with_shared_box_zoom() -> None:
    html = PAGE.read_text(encoding="utf-8")
    navigation_map = html.split(
        "function renderNavigationWorkspaceMap", 1
    )[1].split("function renderNavigationFeatureExtraction", 1)[0]
    navigation_training_map = html.split(
        "function renderNavigationTerrainMap", 1
    )[1].split("function renderNavigationTerrainDetail", 1)[0]
    map_controller = html.split(
        "function createDashboardMapViewportController", 1
    )[1].split("function bindDashboardMapViewports", 1)[0]
    tile_failure_handler = map_controller.split(
        "const onRudyTileGenerationFailed", 1
    )[1].split("const pointInViewport", 1)[0]
    tile_refresh = html.split(
        "function updateDashboardRudyTileLayer", 1
    )[1].split("function updateNavigationRudyTileLayer", 1)[0]
    tile_generation = html.split(
        "function stageDashboardRudyTileGeneration", 1
    )[1].split("function updateDashboardRudyTileLayer", 1)[0]

    for marker in (
        "const DASHBOARD_RUDY_TILE_SOURCE",
        "const NAVIGATION_RUDY_TILE_SOURCE",
        'sourceKind: "scout_proxy_tile"',
        'sourceId: "happyman_rudy_twmap"',
        'cacheLayerId: "imagery"',
        'initialMaxZoom: 13',
        'preparedMaxZoom: 14',
        'maxZoom: 20',
        "function navigationMercatorY(",
        "function navigationRudyTileRange(",
        "function navigationRudyBaseZoom(",
        "function navigationRudyTileUrl(",
        "function navigationRudyTileImages(",
        "function dashboardMapSvgVisibleRatios(",
        "function navigationRudyVisibleBounds(",
        "function renderDashboardRudyTileLayer(",
        "function stageDashboardRudyTileGeneration(",
        "function updateDashboardRudyTileLayer(",
        "function updateNavigationRudyTileLayer(",
        "Math.log2(viewState.zoom)",
        'data-dashboard-rudy-tile-layer="true"',
        'data-navigation-rudy-tile-layer="true"',
        'data-navigation-rudy-tile-zoom="',
        'data-navigation-basemap-layer="rudy-twmap"',
        "updateDashboardRudyTileLayer(viewport, viewState)",
    ):
        assert marker in html

    assert "runtime_href" not in navigation_map
    assert 'data-terrain-overlay="' not in navigation_map
    assert "hillshade" not in navigation_map
    assert "slope_shading" not in navigation_map
    assert "elevation_tint" not in navigation_map
    assert "mouseZoom: false" not in navigation_map
    assert "mouseZoom: false" not in navigation_training_map
    assert "wheelZoom: false" in navigation_map
    assert "wheelZoom: false" in navigation_training_map
    assert 'data-map-control="box-zoom"' in html
    assert "Click or drag in any direction to zoom in" in html
    assert "drag up-left to zoom out" not in html
    assert (
        'const mouseZoomEnabled = viewport.dataset.mapMouseZoom !== "false";'
        in map_controller
    )
    assert (
        'const wheelZoomEnabled = viewport.dataset.mapWheelZoom !== "false";'
        in map_controller
    )
    assert (
        'if (wheelZoomEnabled) viewport.addEventListener("wheel", onWheel, '
        "{passive: false});"
        in map_controller
    )
    assert "Math.ceil(Math.log2(viewState.zoom))" in tile_refresh
    assert "Math.round(Math.log2(viewState.zoom))" not in tile_refresh
    assert "svg.getScreenCTM()" in html
    assert "matrix.inverse()" in html
    assert "dashboardMapSvgVisibleRatios(viewport)" in html
    assert '"/admin/tiles/imagery"' in html
    assert "encodeURIComponent(projectId())" in html
    assert "source_id=${encodeURIComponent(NAVIGATION_RUDY_TILE_SOURCE.sourceId)}&native=1" in html
    assert "let zoom = NAVIGATION_RUDY_TILE_SOURCE.initialMaxZoom" in html
    assert "NAVIGATION_RUDY_TILE_SOURCE.maxZoom," in tile_refresh
    assert "NAVIGATION_RUDY_TILE_SOURCE.preparedMaxZoom," not in tile_refresh
    assert "NAVIGATION_RUDY_TILE_SOURCE.maxZoom - baseZoom" in html
    assert "cached Scout tiles" in html
    assert "tile.happyman.idv.tw" not in html.split(
        "function navigationRudyTileUrl", 1
    )[1].split("function navigationRudyTileLongitude", 1)[0]
    assert "URLSearchParams" not in html.split(
        "function navigationRudyTileUrl", 1
    )[1].split("function navigationRudyTileLongitude", 1)[0]
    assert "tileLayer.innerHTML =" not in tile_refresh
    assert 'data-dashboard-rudy-tile-generation="pending"' in html
    assert 'candidateImage.addEventListener("load"' in tile_generation
    assert 'candidateImage.addEventListener("error"' in tile_generation
    assert 'data-dashboard-rudy-active-map-zoom="1"' in html
    assert 'new CustomEvent("dashboard-rudy-tile-generation-failed"' in tile_generation
    assert "fallbackViewState" in tile_generation
    assert (
        'viewport.addEventListener("dashboard-rudy-tile-generation-failed", '
        "onRudyTileGenerationFailed)"
        in map_controller
    )
    assert 'viewport.dataset.dashboardTileLoadState = "native-unavailable-retained-previous";' in tile_failure_handler
    assert "announce(" in tile_failure_handler
    assert "viewState =" not in tile_failure_handler
    assert "apply(" not in tile_failure_handler
    assert "DASHBOARD_RUDY_TILE_SWAP_TIMEOUT_MS" in tile_generation
    assert "if (loadedCount !== candidateImages.length) return;" in tile_generation
    assert "tileLayer.dataset.dashboardRudyPendingTileKey !== tileKey" in tile_generation
    assert "discardCandidate();" in tile_generation
    assert "promoteCandidate();" in tile_generation
    assert "function discardDashboardPendingRudyTileGeneration(" in html
    assert "if (tileLayer.dataset.dashboardRudyTileKey === tileKey) {" in tile_refresh
    assert "discardDashboardPendingRudyTileGeneration(tileLayer);" in tile_refresh


def test_dashboard_map_zoom_does_not_precompose_dynamic_rudy_tile_stage() -> None:
    html = PAGE.read_text(encoding="utf-8")
    stage_rule = html.split(".dashboard-map-stage {", 1)[1].split("}", 1)[0]

    assert "will-change: transform" not in stage_rule


def test_navigation_architecture_permission_zoom_keep_evidence_screen_sized() -> None:
    html = PAGE.read_text(encoding="utf-8")
    navigation_map = html.split(
        "function renderNavigationWorkspaceMap", 1
    )[1].split("function renderNavigationFeatureExtraction", 1)[0]
    architecture_map = html.split(
        "function architectureMapSlices", 1
    )[1].split("function renderArchitectureEvidenceLedger", 1)[0]
    permission_map = html.split(
        "function renderMapPanel", 1
    )[1].split("function buildMapData", 1)[0]
    map_controller = html.split(
        "function createDashboardMapViewportController", 1
    )[1].split("function bindDashboardMapViewports", 1)[0]

    assert "function updateDashboardMapScreenSymbols(" in html
    assert "function dashboardMapScreenSymbolTransform(" in html
    assert "updateDashboardMapScreenSymbols(viewport, viewState)" in map_controller
    assert "refresh: () => apply()," in map_controller
    assert "focusElements," in map_controller
    assert 'querySelectorAll("[data-dashboard-map-screen-stroke]")' in html
    assert "line.style.strokeWidth" in html
    for renderer in (navigation_map, architecture_map, permission_map):
        assert 'data-dashboard-map-screen-symbol="true"' in renderer
        assert "data-dashboard-map-screen-stroke=" in renderer
        assert 'vector-effect="non-scaling-stroke"' in renderer
    assert 'dashboardMapScreenSymbolTransform("architecture-map"' in architecture_map


def test_dashboard_map_zoom_ceiling_uses_rudy_native_max_matrix() -> None:
    html = PAGE.read_text(encoding="utf-8")
    map_controller = html.split(
        "function createDashboardMapViewportController", 1
    )[1].split("function bindDashboardMapViewports", 1)[0]

    assert "function dashboardMapMaxZoom(" in html
    assert "NAVIGATION_RUDY_TILE_SOURCE.maxZoom - baseZoom" in html
    assert "const maxZoom = dashboardMapMaxZoom(viewport);" in map_controller
    assert "Math.min(maxZoom, Number(saved.zoom) || 1)" in map_controller
    assert "Math.min(maxZoom, viewState.zoom * factor)" in map_controller
    assert "Math.min(12" not in map_controller


def test_dashboard_rectangle_zoom_is_monotonic_persistent_and_clears_selection() -> None:
    html = PAGE.read_text(encoding="utf-8")
    map_controller = html.split(
        "function createDashboardMapViewportController", 1
    )[1].split("function bindDashboardMapViewports", 1)[0]
    map_diagnostic = html.split(
        "function diagnosticExerciseSharedMapController()", 1
    )[1].split("async function diagnosticCheck001()", 1)[0]
    box_zoom = map_controller.split(
        "const finishBoxZoom =", 1
    )[1].split("const onPointerDown =", 1)[0]
    reset = map_controller.split(
        "const reset =", 1
    )[1].split("const setMode =", 1)[0]

    assert "const DASHBOARD_MAP_BOX_ZOOM_MIN_SIZE_PX = 48;" in html
    assert "const DASHBOARD_MAP_BOX_ZOOM_MAX_FACTOR = 4;" in html
    assert "const clearSelection = () => {" in map_controller
    assert 'selection.removeAttribute("style");' in map_controller
    assert 'selection.setAttribute("aria-hidden", "true");' in map_controller
    assert 'selection.setAttribute("aria-hidden", "false");' in map_controller
    assert "boxWidth < DASHBOARD_MAP_BOX_ZOOM_MIN_SIZE_PX" in box_zoom
    assert "boxHeight < DASHBOARD_MAP_BOX_ZOOM_MIN_SIZE_PX" in box_zoom
    assert "Math.min(DASHBOARD_MAP_BOX_ZOOM_MAX_FACTOR" in box_zoom
    assert 'viewState = {...viewState, mode: "pan"};' not in box_zoom
    assert "pointer.lastX < pointer.startX" not in box_zoom
    assert "zoomAt(1 / factor" not in box_zoom
    assert 'mode: "pan"' not in reset
    assert 'viewport.dataset.mapLastGesture = "rectangle-zoom-in";' in box_zoom
    assert "zoomToBox:" in map_controller
    assert "controller.zoomToBox(" in map_diagnostic
    assert "boundedBoxZoomFactor" in map_diagnostic
    assert "reverseDirectionZoomIn" in map_diagnostic
    assert "boxZoomPersists" in map_diagnostic


def test_map_navigation_weather_disable_wheel_zoom_but_keep_box_zoom() -> None:
    html = PAGE.read_text(encoding="utf-8")
    pretrip_html = PRETRIP_PAGE.read_text(encoding="utf-8")
    map_frame_loader = html.split(
        "function ensurePretripMapFrame()", 1
    )[1].split("function ensureAgentChat()", 1)[0]
    map_frame_retry = html.split(
        "function retryPretripMapFrame(frame)", 1
    )[1].split("function adoptPretripMapProjectBridge(frame)", 1)[0]
    weather_map = html.split(
        '<iframe class="weather-cwa-map-frame"', 1
    )[1].split("</iframe>", 1)[0]
    navigation_training_map = html.split(
        "function renderNavigationTerrainMap", 1
    )[1].split("function renderNavigationTerrainDetail", 1)[0]
    navigation_workspace_map = html.split(
        "function renderNavigationWorkspaceMap", 1
    )[1].split("function renderNavigationFeatureExtraction", 1)[0]

    assert "&mapOnly=1&wheelZoom=0" in map_frame_loader
    assert "&mapOnly=1&wheelZoom=0" in map_frame_retry
    assert "&mapOnly=1&wheelZoom=0&initialLayers=" in weather_map
    assert "wheelZoom: false" in navigation_training_map
    assert "wheelZoom: false" in navigation_workspace_map
    assert "mouseZoom: false" not in navigation_training_map
    assert "mouseZoom: false" not in navigation_workspace_map
    assert "const MAP_WHEEL_ZOOM_ENABLED =" in pretrip_html
    assert 'get("wheelZoom") !== "0"' in pretrip_html
    assert (
        'if (MAP_WHEEL_ZOOM_ENABLED) '
        'svg.addEventListener("wheel", handleMapWheelZoom, {passive: false});'
        in pretrip_html
    )


def test_non_main_dashboard_maps_use_only_rudy_tw_basemap_and_disable_wheel_zoom() -> None:
    html = PAGE.read_text(encoding="utf-8")
    surface_contract = html.split(
        "const DASHBOARD_MAP_SURFACES = Object.freeze([", 1
    )[1].split("]);", 1)[0]
    architecture_map = html.split(
        "function renderArchitectureMap", 1
    )[1].split("function renderArchitectureEvidenceLedger", 1)[0]
    pace_map = html.split(
        "function renderPaceFitMiniMap", 1
    )[1].split("function renderRouteContextPage", 1)[0]
    dashboard_preview_map = html.split(
        "function renderMapPanel", 1
    )[1].split("function buildMapData", 1)[0]
    shared_viewport = html.split(
        "function renderDashboardMapViewport", 1
    )[1].split("function createDashboardMapViewportController", 1)[0]

    assert surface_contract.count('basemapPolicy: "full-canonical"') == 1
    assert (
        '{id: "map", route: "map", label: "Map", '
        'family: "canonical-pretrip", basemapPolicy: "full-canonical"}'
        in surface_contract
    )
    assert surface_contract.count('basemapPolicy: "rudy-twmap-only"') == 8

    for marker in (
        "const DASHBOARD_RUDY_TILE_SOURCE",
        "function renderDashboardRudyTileLayer(",
        "function updateDashboardRudyTileLayer(",
        'data-dashboard-rudy-tile-layer="true"',
        'data-map-tile-source="rudy-twmap"',
    ):
        assert marker in html

    assert "renderDashboardRudyTileLayer(" in architecture_map
    assert "architectureTopoGrid" not in architecture_map
    assert 'data-dashboard-basemap-policy="rudy-twmap-only"' in architecture_map
    assert "wheelZoom: false" in architecture_map

    assert "renderDashboardRudyTileLayer(" in pace_map
    assert "paceGrid" not in pace_map
    assert 'data-dashboard-basemap-policy="rudy-twmap-only"' in pace_map
    assert "wheelZoom: false" in pace_map

    for viewport_id in ("overview-map", "lbs-map", "permission-map"):
        assert f'"{viewport_id}"' in dashboard_preview_map
    assert "renderDashboardRudyTileLayer(" in dashboard_preview_map
    assert "SCOUT_LAYER_IDS.map" not in dashboard_preview_map
    assert 'class="map-toolbar"' not in dashboard_preview_map
    assert 'data-dashboard-basemap-policy="rudy-twmap-only"' in dashboard_preview_map
    assert "wheelZoom: false" in dashboard_preview_map
    assert 'renderMapPanel("overview")' in html
    assert 'renderMapPanel("lbs")' in html
    assert 'renderMapPanel("permission")' in html

    assert "const wheelZoomEnabled = options.wheelZoom === true;" in shared_viewport


def test_all_dashboard_maps_enforce_tile_vector_or_approved_single_image_policy() -> None:
    html = PAGE.read_text(encoding="utf-8")
    pretrip_html = PRETRIP_PAGE.read_text(encoding="utf-8")
    pretrip_raster_tiles = pretrip_html.split(
        "function renderRasterLayer(", 1
    )[1].split("function renderOsmTileFallback(", 1)[0]
    pretrip_osm_tiles = pretrip_html.split(
        "function renderOsmTileFallback(", 1
    )[1].split("function renderOsmPbfVector(", 1)[0]
    pretrip_terrain_images = pretrip_html.split(
        "function renderTerrainBitmapOverlays(", 1
    )[1].split("function terrainCellSide(", 1)[0]
    pretrip_cwa_images = pretrip_html.split(
        "function renderCwaWeatherImagery(", 1
    )[1].split("function cwaRainfallCoverageStatus(", 1)[0]
    pretrip_tile_refresh = pretrip_html.split(
        "function renderRasterBasemapLayers(", 1
    )[1].split("function applyMapViewport(", 1)[0]
    navigation_tiles = html.split(
        "function navigationRudyTileImages(", 1
    )[1].split("function renderNavigationRudyTileLayer(", 1)[0]
    dashboard_tile_refresh = html.split(
        "function updateDashboardRudyTileLayer(", 1
    )[1].split("function updateNavigationRudyTileLayer(", 1)[0]
    navigation_training_map = html.split(
        "function renderNavigationTerrainMap", 1
    )[1].split("function renderNavigationTerrainDetail", 1)[0]
    navigation_workspace_map = html.split(
        "function renderNavigationWorkspaceMap", 1
    )[1].split("function renderNavigationFeatureExtraction", 1)[0]
    architecture_map = html.split(
        "function renderArchitectureMap", 1
    )[1].split("function renderArchitectureEvidenceLedger", 1)[0]
    pace_map = html.split(
        "function renderPaceFitMiniMap", 1
    )[1].split("function renderRouteContextPage", 1)[0]
    dashboard_preview_map = html.split(
        "function renderMapPanel", 1
    )[1].split("function buildMapData", 1)[0]

    assert 'data-map-render-policy="tile-vector-approved-single-image"' in pretrip_html
    assert "const MAP_APPROVED_SINGLE_IMAGE_THEMES = Object.freeze(new Set([" in pretrip_html
    assert "function createApprovedSingleImage(" in pretrip_html
    assert "function enforceMapRenderPolicy(" in pretrip_html
    assert "enforceMapRenderPolicy(svg);" in pretrip_html
    for theme in (
        "satellite",
        "radar",
        "lidar",
        "hillshade",
        "elevation_tint",
        "slope_shading",
        "contours",
        "thematic",
    ):
        assert f'"{theme}"' in pretrip_html

    assert '"data-map-render-kind": "tile"' in pretrip_raster_tiles
    assert '"data-map-tile-source": layerId' in pretrip_raster_tiles
    assert '"data-map-render-kind": "tile"' in pretrip_osm_tiles
    assert '"data-map-tile-source": "osm"' in pretrip_osm_tiles
    assert "createApprovedSingleImage(" in pretrip_terrain_images
    assert "if (!image) return;" in pretrip_terrain_images
    assert "createApprovedSingleImage(" in pretrip_cwa_images
    assert "enforceMapRenderPolicy(svg);" in pretrip_tile_refresh

    assert 'data-map-render-kind="tile"' in navigation_tiles
    assert 'data-map-tile-source="rudy-twmap"' in navigation_tiles
    assert "const DASHBOARD_MAP_RENDER_POLICY =" in html
    assert "function enforceDashboardMapRenderPolicy(" in html
    assert "enforceDashboardMapRenderPolicy(viewport);" in html
    assert "renderPolicy: DASHBOARD_MAP_RENDER_POLICY" in navigation_training_map
    assert "renderPolicy: DASHBOARD_MAP_RENDER_POLICY" in navigation_workspace_map
    assert "renderPolicy: DASHBOARD_MAP_RENDER_POLICY" in architecture_map
    assert "renderPolicy: DASHBOARD_MAP_RENDER_POLICY" in pace_map
    assert "renderPolicy: DASHBOARD_MAP_RENDER_POLICY" in dashboard_preview_map
    assert "enforceDashboardMapRenderPolicy(viewport);" in dashboard_tile_refresh


def test_all_dashboard_maps_share_hover_hints_and_keyboard_pan_contract() -> None:
    html = PAGE.read_text(encoding="utf-8")
    map_frame_adapter = html.split(
        "function applyPretripMapOnlyFrame(frame)", 1
    )[1].split("function projectCounts()", 1)[0]
    weather_frame_adapter = html.split(
        "function applyWeatherCwaMapFrame(frame, attempt = 0)", 1
    )[1].split("function bindWeatherCwaMapFrame(frame)", 1)[0]
    navigation_map = html.split(
        "function renderNavigationWorkspaceMap", 1
    )[1].split("function renderNavigationFeatureExtraction", 1)[0]
    architecture_map = html.split(
        "function architectureMapSlices", 1
    )[1].split("function renderArchitectureEvidenceLedger", 1)[0]
    pace_map = html.split(
        "function renderPaceFitMiniMap", 1
    )[1].split("function renderRouteContextPage", 1)[0]
    dashboard_preview_map = html.split(
        "function renderMapPanel", 1
    )[1].split("function buildMapData", 1)[0]

    for marker in (
        'id="dashboardMapHoverHint"',
        'role="tooltip"',
        "function bindDashboardMapHints(",
        "function showDashboardMapHint(",
        "function hideDashboardMapHint(",
        "data-dashboard-map-hint-title",
        "data-dashboard-map-hint-summary",
        "bindDashboardMapHints();",
        'setAttribute("aria-keyshortcuts", "ArrowUp ArrowDown ArrowLeft ArrowRight + - 0 P B Escape")',
    ):
        assert marker in html

    assert "#hoverHint.is-hidden" in map_frame_adapter
    assert "#hoverHint.is-hidden" in weather_frame_adapter
    assert (
        ".route-pane, .detail-pane, #hoverHint { display:none !important; }"
        not in weather_frame_adapter
    )
    assert "#panMode," in map_frame_adapter
    assert "#hoverHint {" in map_frame_adapter
    assert "#hoverHint {" in weather_frame_adapter
    assert 'data-navigation-structure-point-id="' in navigation_map
    assert 'data-navigation-live-point-id="' in navigation_map
    assert 'data-navigation-terrain-event-id="' in navigation_map
    for source in (architecture_map, pace_map, dashboard_preview_map):
        assert "data-dashboard-map-hint-title" in source
        assert "data-dashboard-map-hint-summary" in source
        assert 'tabindex="' in source


def test_dashboard_map_evidence_focus_prefers_exact_candidate_before_shared_source() -> None:
    html = PAGE.read_text(encoding="utf-8")
    focus = html.split("function focusDashboardMapEvidence(sourceId, attempt = 0)", 1)[1].split(
        "function pretripMapHasRenderedTargets", 1
    )[0]

    assert focus.index("item.candidate_id") < focus.index("item.source_id")


def test_dashboard_map_hints_use_dynamic_delegated_events() -> None:
    html = PAGE.read_text(encoding="utf-8")
    binding = html.split("function bindDashboardMapHints(", 1)[1].split(
        "function normalizeDashboardSingleImageTheme", 1
    )[0]

    assert 'root.addEventListener("pointerover"' in binding
    assert 'root.addEventListener("pointermove"' in binding
    assert 'root.addEventListener("pointerout"' in binding
    assert 'root.addEventListener("focusin"' in binding
    assert 'root.addEventListener("focusout"' in binding
    assert 'root.addEventListener("keydown"' in binding
    assert 'closest("[data-dashboard-map-hint-title]")' in binding
    assert "dashboardMapHintDelegatedBound" in binding
    assert "dashboardMapHintBound" not in binding


def test_architecture_dense_labels_meet_dashboard_readability_floor() -> None:
    html = PAGE.read_text(encoding="utf-8")
    architecture_css = html.split("    .route-architecture-shell {", 1)[1].split(
        "    .navigation-terrain-shell {", 1
    )[0]
    pixel_sizes = [
        float(value)
        for value in re.findall(
            r"font(?:-size)?\s*:\s*[^;{}]*?(\d+(?:\.\d+)?)px",
            architecture_css,
        )
    ]

    assert pixel_sizes
    assert min(pixel_sizes) >= 10


def test_weather_layer_status_is_bound_to_the_embedded_render_group() -> None:
    html = PAGE.read_text(encoding="utf-8")
    sync = html.split("function syncWeatherLayerControls", 1)[1].split(
        "function excludeWeatherLayersFromMapFrame", 1
    )[0]

    assert "embeddedPretripLayerRenderState" in html
    assert "renderedItemCount" in sync
    assert 'renderState === "rendered" ? "ON"' in sync
    assert 'renderState === "empty" ? "EMPTY"' in sync
    assert 'button.dataset.weatherLayerRenderState = renderState' in sync


def test_surface_debug_frame_controls_have_visible_semantics() -> None:
    html = PAGE.read_text(encoding="utf-8")
    renderer = html.split("function renderSurfaceFrame", 1)[1].split(
        "function ensurePretripMapFrame", 1
    )[0]
    binder = html.split('const surfaceFrameSkip = document.querySelector', 1)[1].split(
        'document.querySelectorAll("[data-route]")', 1
    )[0]

    assert "data-surface-frame-action-status" in renderer
    assert 'aria-controls="surfaceFrame"' in renderer
    assert "setSurfaceFrameCollapsed" in binder
    assert 'surfaceFrameExit?.addEventListener("click"' in binder
    assert "Returned focus to Dashboard navigation" in binder


def test_scout_dashboard_pace_fit_removes_low_information_blocks() -> None:
    html = PAGE.read_text(encoding="utf-8")

    assert "Readiness & Pace Fit" not in html
    assert 'decisionBand(force.decision, "以最慢成員估算回程 buffer 偏低"' not in html
    assert 'renderMetricPanel("Readiness & Pace Fit"' not in html
    assert 'force.route === "outdoor-pace-fit" ? force.label' in html
    assert 'data-pace-fit-dashboard="true"' in html
    assert '<div class="pace-fit-card-head"><h3>Challenge Fit</h3></div>' not in html
    assert "Pace Controls" not in html
    assert "Pace Parameters" in html
    assert "Read-only preview" in html
    assert "Pace Evidence" in html
    assert "Risk Budget Calculator" in html
    assert "Current CP Status" in html
    assert "CP Timeline" in html
    assert "Pace Object Preview" in html
    assert "Synchronized Map" in html
    assert "slowestMemberBasis" in html
    assert "pace-fit-workbench" in html
    assert "pace-budget-table" in html
    assert "pace-cp-timeline" in html
    assert "pace-mini-map" in html
    assert "Data confidence" not in html


def test_scout_dashboard_pace_fit_is_map_first_and_discloses_supporting_info() -> None:
    html = PAGE.read_text(encoding="utf-8")
    renderer = html.split("function renderPaceFitPage", 1)[1].split(
        "function bodyIndexMetrics", 1
    )[0]
    pace_css = html.split(".pace-fit-dashboard {", 1)[1].split(
        ".body-index-dashboard {", 1
    )[0]

    assert 'data-pace-map-primary="true"' in renderer
    assert 'data-pace-supporting-details="true"' in renderer
    assert (
        '<details class="pace-supporting-details" data-pace-supporting-details="true">'
        in renderer
    )
    assert "pace-spatial-workbench" in renderer
    assert "pace-cp-inspector" in renderer
    assert renderer.index("renderPaceFitPrimaryMap") < renderer.index(
        "Risk Budget Calculator"
    )
    assert renderer.index("renderPaceFitPrimaryMap") < renderer.index(
        "Pace Parameters"
    )
    assert "function paceFitCheckpointContext()" in html
    assert "function paceFitCheckpointMapPoints(" in html
    assert "function bindPaceFitControls()" in html
    assert 'preserveAspectRatio="xMidYMid slice"' in html
    assert 'data-pace-checkpoint-select="${escapeHtml(point.id)}"' in html
    assert "{minimumZoom: 2}" in html
    assert (
        'project: ["home", "timeline", "features-lbs"' in html
        and '"outdoor-pace-fit"' in html.split("const ROUTE_DATA_SCOPES", 1)[1].split(
            "});", 1
        )[0]
    )
    assert "23.120456, 120.832156" not in html
    assert "min-height: clamp(520px, 62vh, 760px)" in pace_css
    assert "height: 210px" not in pace_css


def test_dashboard_truth_metadata_uses_progressive_disclosure() -> None:
    html = PAGE.read_text(encoding="utf-8")
    renderer = html.split("function renderTruthStrip(route)", 1)[1].split(
        "function setRoute", 1
    )[0]

    assert 'class="dashboard-truth-details"' in renderer
    assert 'id="dashboardTruthSummary"' in renderer
    assert 'class="dashboard-truth-panel"' in renderer
    assert '<details class="dashboard-truth-details">' in renderer
    assert '<details class="dashboard-truth-details" open>' not in renderer


def test_scout_dashboard_pace_fit_body_index_dashboard_contract() -> None:
    html = PAGE.read_text(encoding="utf-8")

    for function_name in (
        "bodyIndexMetrics",
        "bodyIndexHealthCoverage",
        "bodyIndexHealthSignals",
        "bodyIndexPressureTimeline",
        "bodyIndexProviderMetrics",
        "bodyIndexStatusPath",
        "bodyIndexWatchStatusPath",
        "bodyIndexImportStatus",
        "bodyIndexWatchStatus",
        "bodyIndexWatchSummary",
        "bodyIndexWatchTone",
        "bodyIndexSummary",
        "bodyIndexRows",
        "bodyIndexScorePercent",
        "bodyIndexDisplayValue",
        "bodyIndexDefaultTrend",
        "normalizeBodyIndexHealthSignal",
        "bodyIndexTrendArrow",
        "bodyIndexTrendPercent",
        "renderBodyIndexSignalTrend",
        "scheduleBodyIndexWatchRefresh",
        "bindBodyIndexControls",
        "renderBodyIndexMetric",
        "renderBodyIndexHealthSignal",
        "renderBodyIndexProviderDrawer",
        "renderPaceFitBodyIndexPage",
    ):
        assert f"function {function_name}" in html

    for marker in (
        'data-route="outdoor-pace-fit-body-index"',
        'if (route === "outdoor-pace-fit-body-index") return renderPaceFitBodyIndexPage();',
        'paceFitSubTabs("outdoor-pace-fit-body-index")',
        'data-body-index-dashboard="true"',
        'data-scout-pace-coefficient="true"',
        'data-body-index-metric="${escapeHtml(metric.id)}"',
        "body-index-dashboard",
        "body-index-summary",
        "body-index-metric-grid",
        "body-index-layout",
        "body-index-ring",
        "body-index-impact-row",
        "body-index-health-strip",
        "body-index-health-grid",
        "body-index-pressure-timeline",
        "body-index-provider-drawer",
        "body-index-provider-grid",
        "body-index-import-button",
        "body-index-import-status",
        "body-index-watch-controls",
        "body-index-watch-button",
        ".body-index-signal-card em",
        "body-index-signal-trend",
        "body-index-trend-axis",
        "body-index-trend-marker",
        "body-index-trend-labels",
        'data-body-index-trend="${escapeHtml(direction)}"',
        'data-health-export-body-index-ui="true"',
        'data-body-index-provider-metrics="collapsed"',
        "BODY_INDEX_FETCH_TIMEOUT_MS = 180000",
        'BODY_INDEX_STATUS_PATH = "/admin/dashboard/body-index"',
        'BODY_INDEX_IMPORT_PATH = "/admin/dashboard/body-index/import"',
        'BODY_INDEX_WATCH_STATUS_PATH = "/admin/dashboard/body-index/watch/status"',
        'BODY_INDEX_WATCH_START_PATH = "/admin/dashboard/body-index/watch/start"',
        'BODY_INDEX_WATCH_STOP_PATH = "/admin/dashboard/body-index/watch/stop"',
        "fetchJson(bodyIndexStatusPath(), { timeoutMs: BODY_INDEX_FETCH_TIMEOUT_MS })",
        "fetchJson(bodyIndexWatchStatusPath())",
        'data-body-index-import',
        'data-body-index-watch-start',
        'data-body-index-watch-stop',
        'data-body-index-watch-controls="true"',
        "state.bodyIndexData = payload",
        "bodyIndexImportBusy",
        "bodyIndexWatchBusy",
        "confirm_import: true",
        "confirm_watch: true",
        "merged ${newCount} new / skipped ${duplicateCount} duplicates",
    ):
        assert marker in html

    for metric_id, english_label, spec_label in (
        ("flat_ground_speed", "Flat Ground Speed", "平地移動速度"),
        ("ascent_speed", "Ascent Speed", "上坡速度"),
        ("descent_speed", "Descent Speed", "下坡速度"),
        ("technical_slowdown", "Technical Terrain Slowdown", "技術地形降速率"),
        ("rest_frequency", "Rest Frequency", "休息頻率"),
        ("late_trip_decay", "Late-trip Decay", "行程後段速度衰退"),
        ("load_impact", "Load Impact", "負重影響"),
        ("weather_impact", "Weather Impact", "天候影響"),
        ("experience_confidence", "Experience Confidence", "經驗可信度"),
    ):
        assert metric_id in html
        assert english_label in html
        assert spec_label in html

    for label in (
        "Scout Pace Coefficient",
        "Energy Reserve",
        "Vulnerability",
        "Experience Trust",
        "Route Impact Mapping",
        "Evidence Matrix",
        "Challenge Fit",
        "slowest member basis",
        "advisory planning",
        "planning evidence",
        "source_provider only",
        "no diagnosis",
        "no Phase 1 mutation",
        "no safety endpoint",
        "no outbound",
        "completed_trip_gpx",
        "route_progress_frame",
        "terrain_time_model",
        "rest_stop_pattern",
        "weather_overlay",
        "team_slowest_member",
        "Body Index Overview",
        "Health Baseline Signals",
        "Window Pressure Timeline",
        "Health Provider Metrics",
        "HealthExport local aggregate",
        "HealthExport-aware",
        "HealthExport import idle",
        "Import HealthExport",
        "Start Watch",
        "watch stopped",
        "Scan sec",
        "Importing local HealthExport zip files",
        "median -- bpm",
        "median -- ms",
        "-- windows",
        "baseline position unavailable",
        "min --",
        "baseline --",
        "avg --",
        "max --",
        "↗",
        "↘",
        "→",
        "HealthAutoExport",
        "Health exports",
        "Walking sessions",
        "GPX tracks",
        "15-min windows",
        "Provider metrics",
        "no HealthExport evidence imported",
        "no sanitized windows imported",
        "No provider metrics imported.",
        "No Scout Pace Coefficient has been calculated.",
        "awaiting evidence",
        "unavailable until evidence import",
        "coefficient_metrics",
        "source value only",
        "not live oxygen uptake",
        "VO2max Baseline",
        "Resting HR",
        "HRV Baseline",
        "Walking HR Average",
        "Active Energy Reset Cue",
        "Recovery Debt Windows",
        "HR Pressure Windows",
        "Step + Distance Pattern",
    ):
        assert label in html


def test_scout_dashboard_moves_pace_fit_emergency_ui_to_safety_emergency() -> None:
    html = PAGE.read_text(encoding="utf-8")
    pace_fit_tabs = html.split("function paceFitSubTabs(activeRoute)", 1)[1].split(
        "function renderPermissionPage", 1
    )[0]

    assert "function paceFitSubTabs(activeRoute)" in html
    assert "Pace Dashboard" in pace_fit_tabs
    assert "Body Index" in pace_fit_tabs
    assert "Emergency UI" not in pace_fit_tabs
    assert 'data-route="outdoor-pace-fit-emergency"' not in html
    assert "function renderPaceFitEmergencyPage()" not in html
    assert 'data-pace-fit-emergency-ui="true"' not in html
    assert ".pace-emergency-shell" not in html
    assert ".pace-emergency-frame" not in html
    assert 'data-route="emergency"' in html
    assert 'data-safety-emergency-console="desktop"' in html


def test_scout_dashboard_safety_emergency_embeds_desktop_approval_console() -> None:
    html = PAGE.read_text(encoding="utf-8")
    emergency_page = html.split("function renderEmergencyPage()", 1)[1].split(
        "function renderDebugPage()", 1
    )[0]
    permission_loader = html.split("async function loadPermissionData()", 1)[1].split(
        "function stopNavigationTerrainPolling", 1
    )[0]

    assert 'data-route="emergency"' in html
    assert 'data-safety-emergency-console="desktop"' in emergency_page
    assert 'data-daily-emergency-review="ready"' in emergency_page
    assert 'data-emergency-decision="${decision}"' in emergency_page
    assert 'data-emergency-confirm-submit="true"' in html
    assert 'data-emergency-approval-frame="desktop"' in emergency_page
    assert 'src="/admin/dashboard/emergency-approval-desktop-v0"' in emergency_page
    assert 'title="Legacy safety and emergency desktop approval console"' in emergency_page
    assert "emergency-mobile-approval-v0" not in emergency_page
    assert 'renderMapPanel("emergency")' in emergency_page
    assert ".safety-emergency-shell" in html
    assert ".safety-emergency-frame" in html
    assert '<header class="safety-emergency-commandbar">' not in emergency_page
    assert 'class="safety-emergency-status-grid"' not in emergency_page
    assert "safety-emergency-status-card" not in emergency_page
    assert "safety-emergency-eyebrow" not in emergency_page
    assert ".safety-emergency-commandbar" not in html
    assert ".safety-emergency-status-grid" not in html
    assert ".safety-emergency-status-card" not in html
    assert "if (projection?.daily_review?.mission_day_instance_id)" in permission_loader
    assert 'projection?.status === "ready" &&' not in permission_loader


def test_contextual_permission_workbench_uses_typed_projection_and_dedicated_scope() -> None:
    html = PAGE.read_text(encoding="utf-8")
    permission_page = html.split("function renderPermissionPage(force)", 1)[1].split(
        "function weatherImageryFrames", 1
    )[0]
    permission_loader = html.split("async function loadPermissionData()", 1)[1].split(
        "function stopNavigationTerrainPolling", 1
    )[0]
    simulation = html.split("async function runPermissionCandidateSimulation()", 1)[
        1
    ].split("async function previewPermissionBaseline(", 1)[0]

    assert 'permission: ["outdoor-permission", "emergency"]' in html
    assert 'permissionLens: "baseline"' in html
    assert "contextual-permission-dashboard?lens=" in html
    assert 'state.route === "emergency"\n          ? "replay"' in permission_loader
    assert "state.permissionProjection = projection;" in permission_loader
    assert (
        "await loadPermissionBaselineMapContext(\n"
        "          state.pretripDataProjectId || projectId(),\n"
        "        );"
    ) in permission_loader
    assert "state.permissionReviewSession = await fetchJson" in permission_loader
    assert 'projection.status === "blocked"' in permission_page
    assert "renderPermissionBaselineAuthoring()" in permission_page
    assert "Rebuild from reviewed baseline" in permission_page
    assert "Rebuild after new proposal" in permission_page
    assert "data-permission-projection-rebuild" in html
    assert "contextual-permission-dashboard/rebuilds" in html
    assert "expected_admission_snapshot_sha256" in html
    assert "expected_evaluator_version" in html
    assert "rules remain review_only" in html
    assert 'data-contextual-permission-workbench="${isDegraded ? "degraded" : "ready"}"' in permission_page
    assert "Permission bootstrap needs itinerary review" in permission_page
    assert "if (projection.status !== \"ready\")" not in permission_page
    assert "Remaining Mission Projection" in permission_page
    assert "Risk-Budget Ledger" in permission_page
    assert "Event & Evidence Ledger" in permission_page
    assert "Day, Movement Groups & Communication" in permission_page
    assert "Safety / Emergency" in permission_page
    assert "Baseline Authoring Workbench" in html
    assert "Scout auto proposal" in html
    assert "Quick review" in html
    assert "mission-baseline/map-context" in html
    assert "mission-baseline/rudy-background.png" in html
    assert "data-permission-day-map" in html
    assert 'data-permission-rudy-background="true"' in html
    assert 'data-rudy-image-policy="single-composite"' in html
    assert "permission-day-grid" in html
    assert "permissionDayAnchorContext" in html
    assert "permissionDailyLabelAnchors" in html
    assert 'anchor.source_kind === "mcp"' in html
    assert "permissionFormatCoordinate" in html
    assert "Day route, ETA & evidence" in html
    assert 'data-permission-projection-details="true"' in permission_page
    ready_page = permission_page.split("const isDegraded", 1)[1]
    assert ready_page.index("${renderPermissionBaselineAuthoring()}") < ready_page.index(
        'data-permission-projection-details="true"'
    )
    assert "Mobile quick flow" in permission_page
    assert "Pending Safety / Emergency" in html
    assert "reviewed_day_ids" in html
    assert "acknowledged_uncertainty_ids" in html
    assert "safety_handoff_acknowledged" in html
    assert "Typed evidence payload" in html
    assert "Run candidate simulation" in permission_page
    assert "candidate_only=true" in permission_page
    assert 'data-emergency-decision=' not in permission_page
    assert "state.permissionProjection = result.projection" not in simulation
    assert "Current Decision not replaced" in simulation
    assert 'force: route === "emergency" || route === "outdoor-permission"' in html


def test_daily_emergency_review_is_shared_fail_closed_and_two_step() -> None:
    html = PAGE.read_text(encoding="utf-8")
    emergency_page = html.split("function renderEmergencyPage()", 1)[1].split(
        "function renderDebugPage()", 1
    )[0]
    emergency_submit = html.split("async function submitEmergencyReviewDecision()", 1)[
        1
    ].split("function bindPermissionControls()", 1)[0]
    permission_bindings = html.split("function bindPermissionControls()", 1)[1].split(
        "function bindRenderedControls()", 1
    )[0]

    for decision in (
        "select_hold_or_bivy",
        "reject_night_travel",
        "approve_for_runtime_consideration",
        "escalate_emergency",
    ):
        assert decision in emergency_page
    for view in ("decision", "field", "gates", "evidence"):
        assert f'["{view}",' in emergency_page
    assert 'data-emergency-evidence-map="true"' in emergency_page
    assert '["map",' not in emergency_page
    assert "No write occurs on the first tap" in emergency_page
    assert 'data-emergency-confirm-submit="true"' in html
    assert "explicit_confirmation: true" in emergency_submit
    assert "packet_sha256: packet.sha256" in emergency_submit
    assert "review_generation: packet.review_generation" in emergency_submit
    assert "reviewed_sequence: packet.reviewed_sequence" in emergency_submit
    assert "state.emergencyPendingDecision = {" in permission_bindings
    assert "postJson(" not in permission_bindings.split(
        'document.querySelectorAll("[data-emergency-decision]")', 1
    )[1].split(
        'document.querySelector("[data-emergency-confirm-submit]")', 1
    )[0]
    assert "runtime_authorization_performed=false" in emergency_page
    assert "outbound_action_performed=false" in emergency_page
    assert "outbound_transport_invoked=false" in emergency_page
    assert "external_send_performed=false" in emergency_page


def test_emergency_field_state_exposes_od013_through_od018_without_night_packet_lockout() -> None:
    html = PAGE.read_text(encoding="utf-8")
    emergency_page = html.split("function renderEmergencyPage()", 1)[1].split(
        "function renderDebugPage()", 1
    )[0]
    field_submit = html.split("async function submitEmergencyFieldAction(", 1)[1].split(
        "async function submitEmergencyReviewDecision()", 1
    )[0]
    bindings = html.split("function bindPermissionControls()", 1)[1].split(
        "function bindRenderedControls()", 1
    )[0]

    assert "const reviewPacket" in emergency_page
    assert "Field operations remain available" in emergency_page
    assert 'data-emergency-field-operations="true"' in emergency_page
    assert 'data-emergency-field-action="complete_day"' in emergency_page
    assert 'data-emergency-field-action="wrong_target"' in emergency_page
    assert 'data-emergency-field-action="cannot_reach_target"' in emergency_page
    assert 'data-emergency-field-action="select_bivy"' in emergency_page
    assert 'data-emergency-shelter-hold-card="true"' in emergency_page
    assert 'data-emergency-departure-checklist="true"' in emergency_page
    assert 'data-emergency-field-action="start_day"' in emergency_page
    assert "required_seconds || 600" in emergency_page
    assert "No leader sleep roll call" in emergency_page
    assert "No continuous heartbeat required" in emergency_page
    assert "My group" in emergency_page and "All groups" in emergency_page
    for suffix in (
        '"day-end/confirm"',
        '"day-end/corrections"',
        '"day-end/unreachable"',
        '"arrival-dwell"',
        '"emergency-bivy/selection"',
        '"shelter-hold/reviews"',
        '"mission-day-starts"',
        '"field-conflicts"',
    ):
        assert suffix in field_submit
    first_tap = bindings.split(
        'document.querySelectorAll("[data-emergency-field-action]")', 1
    )[1].split(
        'document.querySelector("[data-emergency-conflict-note]")', 1
    )[0]
    assert "state.emergencyPendingFieldAction = {" in first_tap
    assert "postJson(" not in first_tap
    assert 'data-emergency-field-confirm-submit="true"' in html


def test_baseline_authoring_supports_generate_patch_lineage_and_review_ready_gate() -> None:
    html = PAGE.read_text(encoding="utf-8")
    baseline_submit = html.split("async function previewPermissionBaseline(", 1)[1].split(
        "function emergencyReviewDecisionPath", 1
    )[0]
    baseline_page = html.split('data-permission-baseline-authoring="true"', 1)[1].split(
        '<div class="permission-boundary-banner">', 1
    )[0]

    assert '"generate-draft" : "preview"' in baseline_submit
    assert "/mission-baseline/patches/preview" in baseline_submit
    assert "/mission-baseline/candidates/from-patch" in baseline_submit
    assert "conversation_hashes" in baseline_submit
    assert 'operation: "add_assumption"' in baseline_submit
    assert 'data-permission-baseline-patch-panel="true"' in baseline_page
    assert "Preview Scout patch" in baseline_page
    assert "Save patch as new version" in baseline_page
    assert "review_ready === true" in baseline_page
    assert "free text cannot silently clear them" in baseline_page


def test_offline_emergency_review_uses_encrypted_local_intents_before_sync() -> None:
    html = PAGE.read_text(encoding="utf-8")
    storage = html.split('const EMERGENCY_OFFLINE_DB =', 1)[1].split(
        "function stopConnectedPreparationPolling", 1
    )[0]
    submit = html.split("async function submitEmergencyReviewDecision()", 1)[1].split(
        "function bindPermissionControls()", 1
    )[0]
    field_submit = html.split("async function submitEmergencyFieldAction", 1)[1].split(
        "async function submitEmergencyReviewDecision", 1
    )[0]

    assert 'generateKey(\n        {name: "AES-GCM", length: 256}' in storage
    assert 'false,\n        ["encrypt", "decrypt"]' in storage
    assert "window.crypto.subtle.encrypt" in storage
    assert 'database.createObjectStore("offline_intents"' in storage
    assert "device_local_encrypted: true" in storage
    assert "/offline-intents/sync" in storage
    assert "rebuildPermissionTruthAndSyncOfflineIntents" in storage
    assert 'navigator.onLine === false' in submit
    assert "saveEmergencyOfflineIntent(packet, pending)" in submit
    assert "Offline approval is forbidden" in storage
    assert "no server receipt" in html
    assert "saveEmergencyOfflineFieldCompletion" in storage
    assert 'intent_type: "field_day_end_completion"' in storage
    assert "saveEmergencyOfflineFieldConflict" in storage
    assert 'intent_type: "field_conflict"' in storage
    assert "/day-end/offline-intents/sync" in storage
    assert "/field-conflicts/offline-intents/sync" in storage
    assert "/movement-groups/offline-intents/sync" in storage
    assert "uncertainty_acknowledgement: true" in storage
    assert '["complete_day", "field_conflict"].includes(pending.action)' in field_submit
    assert "blocked locally by encrypted" in field_submit
    assert 'displayedState = offlineConflict ? "blocked_pending_sync"' in html
    assert "server row is unchanged" in html
    assert 'data-emergency-offline-field-result="true"' in html
    assert "field receipt recorded; projection refresh pending" in storage


def test_permission_lens_switch_renders_after_successful_projection_reload() -> None:
    html = PAGE.read_text(encoding="utf-8")
    controls = html.split("function bindPermissionControls()", 1)[1].split(
        'document.querySelectorAll("[data-permission-mobile-view]")', 1
    )[0]

    assert 'await loadDataScope("permission", {force: true});' in controls
    assert controls.count('if (state.route === "outdoor-permission") render();') == 2


def test_permission_and_emergency_mobile_controls_remain_large_and_complete() -> None:
    html = PAGE.read_text(encoding="utf-8")
    styles = html.split("<style>", 1)[1].split("</style>", 1)[0]

    assert "@media (max-width: 760px)" in styles
    assert ".permission-mobile-switcher" in styles
    assert ".emergency-review-switcher" in styles
    assert "font-size: 16px;" in styles
    assert "min-height: 56px;" in styles
    assert ".emergency-group-toggle button { font-size: 16px; }" in styles
    assert "font-size: 16px;\n        letter-spacing: 0;" in styles
    assert "padding-inline: 2px;\n        white-space: nowrap;\n        overflow-wrap: normal;" in styles
    assert ".emergency-gate-row strong {\n        flex: 0 0 auto;\n        white-space: nowrap;" in styles
    assert "grid-template-columns: repeat(4, minmax(0, 1fr));" in styles
    assert ".permission-pane:not(.is-mobile-active)" in styles
    assert ".emergency-review-pane:not(.is-mobile-active)" in styles
    assert "overflow-x: hidden;" in styles
    assert "Mobile quick flow" in html
    assert 'class="permission-card" data-permission-baseline-authoring="true"' in html
    assert "complete at most three checks, then accept" in html
    assert ".permission-day-grid" in styles
    assert "grid-template-columns: repeat(2, minmax(0, 1fr));" in styles
    assert ".permission-day-grid { grid-template-columns: 1fr; }" in styles


def test_scout_dashboard_route_context_embeds_skill_trip_briefing() -> None:
    html = PAGE.read_text(encoding="utf-8")
    controls = html.split(
        "function bindRouteContextBriefingControls()", 1
    )[1].split("function bindDebugDetailControls()", 1)[0]
    regeneration_controls = controls
    available_artifact = html.split(
        'if (artifactStatus.status === "available") {', 1
    )[1].split('if (artifactStatus.status === "missing") {', 1)[0]

    assert "function routeContextBriefingProjectId()" in html
    assert "function routeContextBriefingSrc()" in html
    assert "function renderRouteBriefingMetaBlock" in html
    assert "return projectId();" in html
    assert 'return route === "agent" || route === "debug" || route === "diagnostic" || route === "runtime-audit" || route === "emergency" || route === "outdoor-route-context" || route === "outdoor-pace-fit" || route === "outdoor-pace-fit-body-index";' in html
    assert 'decisionBand(force.decision, "Scout AI route-context trip briefing loaded"' not in html
    assert "/admin/pretrip/projects/${project}/briefings/route-context" in html
    assert "data-route-context-briefing=\"true\"" in html
    assert 'class="route-briefing-inline-document"' in html
    assert "route-briefing-inline-document-header" not in html
    assert "data-route-context-briefing-inline-status" not in html
    assert "完整 Route Context 導覽" not in html
    assert "完整內容載入中…" not in html
    assert "完整內容已在本頁展開，可使用 Dashboard 捲軸一路閱讀至頁尾。" not in html
    assert "完整內容已載入；目前使用內嵌捲動顯示。" not in html
    assert "${escapeHtml(briefingProject)}" not in available_artifact
    assert 'scrolling="no"' in html
    assert "function syncRouteContextBriefingFrameHeight(frame)" in html
    assert "function bindRouteContextBriefingFrame(frame)" in html
    assert "documentRef.documentElement?.scrollHeight" in html
    assert "frame.dataset.routeContextBriefingHeight = String(nextHeight);" in html
    assert "new ResizeObserver(sync)" in html
    assert "bindRouteContextBriefingFrame(routeContextBriefingFrame);" in html
    assert 'class="route-briefing-meta-drawer" data-route-briefing-metadata="collapsed"' in html
    assert '<details class="route-briefing-meta-drawer" data-route-briefing-metadata="collapsed" open>' not in html
    assert "Briefing metadata" in html
    assert "route-briefing-meta-grid" in html
    assert "route-briefing-meta-block" in html
    assert "Scout AI Trip Briefing" not in html
    assert "route-briefing-ops" in html
    assert "data-route-context-briefing-regenerate" in html
    assert "重新產生並審核" in html
    assert "/briefings/route-context/regenerate" in html
    assert "function routeContextBriefingVariantsPath()" in html
    assert "function routeContextBriefingVariantsGeneratePath()" in html
    assert "function routeContextBriefingVariantFileSrc(ref)" in html
    assert "/briefings/route-context/variants" in html
    assert "/briefings/route-context/variants/generate" in html
    assert "data-route-context-briefing-variants-generate" not in html
    assert "Generate 5 variants with Scout AI" not in html
    assert "Generating 5 variants..." not in html
    assert "Calling Scout AI route-context-intelligence skill for five variants" not in html
    assert "reference similarity" in html
    assert "reference_similarity_gate" in html
    assert "Open variants index" in html
    assert "Model audit" in html
    assert "single Scout AI model call" in html
    assert "canonical briefing unchanged" in html
    assert "輸入契約 → 證據收集 → 確定性編譯 → DeepSeek 內容審核" in html
    assert 'model: "deepseek/deepseek-v3.2"' in html
    assert "canonical_promoted" in html
    assert 'payload.review?.verdict === "PASS"' in html
    assert "payload.generation?.editorial_contract?.status" in html
    assert "payload.generation?.model_request_count" in html
    assert "確定性內容門檻" in html
    assert "審核未通過，已保留前一版" in html
    assert "timeoutMs: ROUTE_CONTEXT_REGENERATION_TIMEOUT_MS" in html
    assert "await loadRouteContextBriefingArtifactStatus();" in regeneration_controls
    assert "await loadData();" not in regeneration_controls
    assert "Calling Scout AI via OpenRouter" not in html
    assert "Open briefing" in html
    assert "outputs/briefings/route_context_briefing.html" in html
    assert "scout-route-context-briefing skill" in html
    assert "輸入契約 → 證據收集 → 確定性編譯 → 內容審核" in html
    assert "candidate-only" in html
    assert "runtime_safety_truth=false" in html
    assert "stop permission, route open/closed decision" in html
    assert "no Phase 1 mutation, no safety endpoint write" in html
    assert '["Outbound", "closed"]' in html
    assert "no live safety automation" not in html
    assert '<div class="debug-main-stack">\n            ${renderMetricPanel("Briefing Source"' not in html


def test_dashboard_route_context_binds_selected_project_before_first_render() -> None:
    html = PAGE.read_text(encoding="utf-8")
    project_binding = html.split(
        "function routeContextBriefingProjectId()", 1
    )[1].split("function routeContextBriefingSrc()", 1)[0]

    assert "pretripDataProjectId: projectId()," in html
    assert "pretripDataProjectId: PROJECT_ID," not in html
    assert "return projectId();" in project_binding
    assert "PRETRIP_DATA_PROJECT_ID" not in project_binding


def test_dashboard_route_context_reports_canonical_briefing_availability() -> None:
    html = PAGE.read_text(encoding="utf-8")
    status_loader = html.split(
        "async function loadRouteContextBriefingArtifactStatus()", 1
    )[1].split("async function loadBodyIndexData()", 1)[0]

    assert '<link rel="icon" href="data:">' in html
    for marker in (
        "briefingArtifactStatus",
        "function routeContextBriefingStatusPath()",
        "function loadRouteContextBriefingArtifactStatus()",
        "/briefings/route-context/status",
        'status: "checking"',
        'data-route-context-briefing-state="missing"',
        "Route briefing unavailable for this workspace",
        "No Scout AI request was started.",
        "Canonical briefing missing",
        "Artifact exists · content quality not approved",
    ):
        assert marker in html

    assert "Existing artifacts verified" not in html
    assert "fetchJson(routeContextBriefingStatusPath())" in status_loader
    assert '["available", "missing"].includes(status)' in status_loader
    assert 'status === "available"' in status_loader
    assert "routeContextBriefingSrc()" not in status_loader
    assert 'artifactStatus.status === "available"' in html
    assert "Only a hash-bound PASS replaces and reloads the canonical briefing" in html
    assert "If the frame is empty, regenerate the route-context briefing artifact" not in html


def test_scout_dashboard_emergency_boundary_and_mobile_independence_contract() -> None:
    html = PAGE.read_text(encoding="utf-8")

    assert "Emergency Package Draft only" not in html
    assert "mobile approval UI remains independent" not in html
    assert "sent=false" in html
    assert "external_send_performed=false" in html
    assert "/safety/" not in html
    assert "fetch(`${apiBase()}${path}`" in html
    assert 'method: "POST"' in html
    assert "/briefings/route-context/regenerate" in html
    assert "confirm_regenerate: true" in html


def test_scout_dashboard_layer_contract_ids_are_present() -> None:
    html = PAGE.read_text(encoding="utf-8")
    pretrip_html = PRETRIP_PAGE.read_text(encoding="utf-8")

    expected_layers = (
        "imagery",
        "rudy",
        "rudy-twmap",
        "relief",
        "geology",
        "topo-5k",
        "forest",
        "osm",
        "terrain",
        "corridors",
        "overpass",
        "route",
        "completed-track",
        "reference-tracks",
        "retreat",
        "segments",
        "risk-ribbon",
        "risk-heatmap",
        "risk-delta",
        "soil-moisture",
        "antecedent-rain",
        "cwa-qpf",
        "risk-score",
        "checkpoints",
        "pois",
        "hazards",
        "route-notes",
        "cwa-weather",
        "mcp",
        "boss-points",
        "events",
        "weather-api",
    )
    for layer_id in expected_layers:
        assert f'"{layer_id}"' in html
    assert "SCOUT_LAYER_IDS" in html
    assert "input type=\"checkbox\" data-layer" not in html
    assert "input type=\"checkbox\" data-layer" in pretrip_html
    assert "use the main Map for the complete layer contract" in html
    assert "data-layer-group" in html


def _write_body_index_health_export_zip(
    path: Path,
    *,
    day: str,
    workout_id: str,
    hour: int,
) -> Path:
    payload = {
        "data": {
            "workouts": [
                _body_index_walk_workout(
                    workout_id,
                    day=day,
                    hour=hour,
                    distances_km=[0.72, 0.89, 0.8],
                    step_counts=[1072, 1250, 1260],
                    active_energy_kj=[100, 110, 100],
                    heart_rates=[100] * 15 + [101] * 15 + [94] * 15,
                )
            ],
            "metrics": [
                _body_index_metric("vo2_max", [36.9, 37.1]),
                _body_index_metric("heart_rate_variability", [42.4, 34.1]),
                _body_index_metric("resting_heart_rate", [72]),
                _body_index_metric("walking_heart_rate_average", [106]),
            ],
        }
    }
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("HealthAutoExport-body-index.json", json.dumps(payload, ensure_ascii=False))
        archive.writestr(
            "private-route.gpx",
            '<gpx><trk><trkseg><trkpt lat="40.0" lon="116.0" /></trkseg></trk></gpx>',
        )
    return path


def _body_index_walk_workout(
    workout_id: str,
    *,
    day: str,
    hour: int,
    distances_km: list[float],
    step_counts: list[int],
    active_energy_kj: list[int],
    heart_rates: list[int],
) -> dict[str, object]:
    duration_min = len(distances_km) * 15
    end_hour = hour + duration_min // 60
    end_min = duration_min % 60
    distance_rows: list[dict[str, object]] = []
    step_rows: list[dict[str, object]] = []
    energy_rows: list[dict[str, object]] = []
    hr_rows: list[dict[str, object]] = []
    for minute in range(duration_min):
        window = minute // 15
        row_date = f"{day} {hour + minute // 60:02d}:{minute % 60:02d}:00 +0800"
        distance_rows.append(
            {
                "date": row_date,
                "qty": distances_km[window] / 15.0,
                "units": "km",
                "source": "fixture.watch",
            }
        )
        step_rows.append(
            {
                "date": row_date,
                "qty": step_counts[window] / 15.0,
                "units": "count",
                "source": "fixture.watch",
            }
        )
        energy_rows.append(
            {
                "date": row_date,
                "qty": active_energy_kj[window] / 15.0,
                "units": "kJ",
                "source": "fixture.watch",
            }
        )
        hr_rows.append(
            {
                "date": row_date,
                "Avg": heart_rates[minute],
                "Max": heart_rates[minute],
                "Min": heart_rates[minute],
                "units": "bpm",
                "source": "fixture.watch",
            }
        )
    return {
        "id": workout_id,
        "name": "步行",
        "start": f"{day} {hour:02d}:00:00 +0800",
        "end": f"{day} {end_hour:02d}:{end_min:02d}:00 +0800",
        "duration": duration_min * 60,
        "distance": {"qty": sum(distances_km), "units": "km"},
        "avgHeartRate": {
            "qty": round(sum(heart_rates) / len(heart_rates), 1),
            "units": "bpm",
        },
        "maxHeartRate": {"qty": max(heart_rates), "units": "bpm"},
        "activeEnergyBurned": {"qty": sum(active_energy_kj), "units": "kJ"},
        "walkingAndRunningDistance": distance_rows,
        "stepCount": step_rows,
        "activeEnergy": energy_rows,
        "heartRateData": hr_rows,
        "route": [
            {
                "latitude": 40.0,
                "longitude": 116.0,
                "altitude": 600,
                "timestamp": f"{day}T{hour:02d}:00:00+08:00",
            }
        ],
    }


def _body_index_metric(name: str, values: list[float]) -> dict[str, object]:
    return {
        "name": name,
        "data": [{"qty": value, "source": "fixture.watch"} for value in values],
    }


def test_dashboard_cwa_truth_state_play_guard_and_single_product_contract() -> None:
    html = PAGE.read_text(encoding="utf-8")
    pretrip_html = PRETRIP_PAGE.read_text(encoding="utf-8")

    for marker in (
        "CWA_UI_STATUSES",
        "dashboardCwaDerivedStatus",
        "stale_data",
        "no_coverage",
        "zero_precipitation",
        "unavailable",
        "formatCwaTimestamp",
        'data-weather-cwa-rainfall-product="true"',
        'data-weather-cwa-play="true"',
        "weatherRainfallProduct",
    ):
        assert marker in html

    assert 'weatherCwaProduct: "radar"' in html
    assert "play.disabled = Number(snapshot.maxFrameIndex || 0) < 1;" in html
    assert "rainfallStatus.textContent = dashboardCwaRainfallStatusText" in html
    assert "function cwaDerivedStatus" in pretrip_html
    assert 'productId: "radar"' in pretrip_html
    assert "playableFrameCount < 2" in pretrip_html
    assert "button.disabled = playableFrameCount < 2" in pretrip_html
    assert "freshness:" in pretrip_html
    assert "coverageStatus:" in pretrip_html


def test_weather_cwa_playback_uses_direct_stop_and_lightweight_tick_sync() -> None:
    pretrip_html = PRETRIP_PAGE.read_text(encoding="utf-8")

    playback_sync = pretrip_html.split(
        "function syncCwaImageryPlaybackControls()", 1
    )[1].split("function syncCwaImageryControls()", 1)[0]
    playback_transition = pretrip_html.split(
        "function setCwaImageryPlaying(playing)", 1
    )[1].split("function bindCwaWeatherImageryControls()", 1)[0]
    controller = pretrip_html.split(
        "window.scoutCwaImageryController = Object.freeze({", 1
    )[1].split("function renderProjectView(view)", 1)[0]

    assert "data-cwa-imagery-timeline" in playback_sync
    assert "data-cwa-imagery-play" in playback_sync
    assert "clearInterval(cwaImageryUi.playTimer);" in playback_transition
    assert "cwaImageryUi.playTimer = null;" in playback_transition
    assert "syncCwaImageryPlaybackControls();" in playback_transition
    interval_tick = playback_transition.split("setInterval(() => {", 1)[1].split(
        "}, 700);", 1
    )[0]
    assert "syncCwaImageryPlaybackControls();" in interval_tick
    assert "syncCwaImageryControls();" not in interval_tick
    assert "return setCwaImageryPlaying(Boolean(playing));" in controller
    assert 'document.querySelector("[data-cwa-imagery-play]")?.click()' not in controller


def test_weather_cwa_playback_stop_clears_timer_and_can_restart() -> None:
    pretrip_html = PRETRIP_PAGE.read_text(encoding="utf-8")
    playback_sync = "function syncCwaImageryPlaybackControls()" + pretrip_html.split(
        "function syncCwaImageryPlaybackControls()", 1
    )[1].split("function syncCwaImageryControls()", 1)[0]
    playback_transition = "function setCwaImageryPlaying(playing)" + pretrip_html.split(
        "function setCwaImageryPlaying(playing)", 1
    )[1].split("function bindCwaWeatherImageryControls()", 1)[0]
    node_program = "\n".join(
        (
            """
const timelines = [{max: "", value: "", disabled: false}];
const buttons = [{disabled: false, textContent: "Play", attrs: {}, setAttribute(name, value) { this.attrs[name] = value; }}];
const document = {querySelectorAll(selector) {
  if (selector === "[data-cwa-imagery-timeline]") return timelines;
  if (selector === "[data-cwa-imagery-play]") return buttons;
  return [];
}};
const frames = [{id: 0}, {id: 1}, {id: 2}];
const cwaImageryUi = {frameIndex: 0, playTimer: null};
const timers = new Map();
let nextTimer = 1;
let publishCalls = 0;
let renderCalls = 0;
function cwaImageryFrames() { return frames; }
function setInterval(callback, delay) { const id = nextTimer++; timers.set(id, {callback, delay}); return id; }
function clearInterval(id) { timers.delete(id); }
function publishCwaImageryState() { publishCalls += 1; }
function renderCurrentCwaImagerySurface() { renderCalls += 1; }
function cwaImageryStateSnapshot() {
  return {frameIndex: cwaImageryUi.frameIndex, maxFrameIndex: frames.length - 1, playing: Boolean(cwaImageryUi.playTimer)};
}
""",
            playback_sync,
            playback_transition,
            """
const started = setCwaImageryPlaying(true);
const firstTimer = cwaImageryUi.playTimer;
timers.get(firstTimer).callback();
const frameAfterFirstTick = cwaImageryUi.frameIndex;
const stopped = setCwaImageryPlaying(false);
const stoppedFrame = cwaImageryUi.frameIndex;
const firstTimerStillActive = timers.has(firstTimer);
const stoppedButton = {text: buttons[0].textContent, pressed: buttons[0].attrs["aria-pressed"]};
const restarted = setCwaImageryPlaying(true);
const secondTimer = cwaImageryUi.playTimer;
timers.get(secondTimer).callback();
const frameAfterRestartTick = cwaImageryUi.frameIndex;
setCwaImageryPlaying(false);
process.stdout.write(JSON.stringify({
  started,
  firstTimer,
  frameAfterFirstTick,
  stopped,
  stoppedFrame,
  firstTimerStillActive,
  stoppedButton,
  restarted,
  secondTimer,
  frameAfterRestartTick,
  finalTimer: cwaImageryUi.playTimer,
  publishCalls,
  renderCalls
}));
""",
        )
    )

    result = subprocess.run(
        ["node"],
        input=node_program,
        text=True,
        capture_output=True,
        check=True,
    )
    payload = json.loads(result.stdout)

    assert payload["started"]["playing"] is True
    assert payload["frameAfterFirstTick"] == 1
    assert payload["stopped"]["playing"] is False
    assert payload["stoppedFrame"] == 1
    assert payload["firstTimerStillActive"] is False
    assert payload["stoppedButton"] == {"text": "Play", "pressed": "false"}
    assert payload["restarted"]["playing"] is True
    assert payload["secondTimer"] != payload["firstTimer"]
    assert payload["frameAfterRestartTick"] == 2
    assert payload["finalTimer"] is None
    assert payload["renderCalls"] == 2
    assert payload["publishCalls"] >= 6


def test_architecture_modebar_allows_only_component_local_horizontal_scroll() -> None:
    html = PAGE.read_text(encoding="utf-8")

    modebar_style = html.split(
        ".architecture-modebar,", 1
    )[1].split(".architecture-modebar {", 1)[0]
    architecture = html.split(
        "function renderArchitecturePage(force)", 1
    )[1].split("function renderRuntimeAuditPage", 1)[0]

    assert "overflow-x: auto;" in modebar_style
    assert "overscroll-behavior-inline: contain;" in modebar_style
    assert 'data-overflow-contract="horizontal-scroll"' in architecture
    assert 'role="tablist" aria-label="Route architecture analysis modes"' in architecture


def test_dashboard_open_only_reads_connected_preparation_status() -> None:
    html = PAGE.read_text(encoding="utf-8")
    startup = html.split(
        'document.addEventListener("DOMContentLoaded", () => {', 1
    )[1].split("function apiBase()", 1)[0]
    status_loader = html.split(
        "async function loadConnectedPreparationStatus()", 1
    )[1].split("async function triggerDashboardConnectedPreparation", 1)[0]

    assert "void loadConnectedPreparationStatus();" in startup
    assert 'triggerDashboardConnectedPreparation("dashboard-open")' not in startup
    assert "fetchJson(" in status_loader
    assert "postJson(" not in status_loader
    assert "refreshCurrentDataView();" in status_loader


def test_dashboard_weather_route_consumes_cache_only_live_cwa_data() -> None:
    html = PAGE.read_text(encoding="utf-8")

    for marker in (
        "function loadWeatherData",
        "function weatherCandidateSnapshot",
        "function weatherDecisionReadiness",
        "!snapshot.preferredRainfall && !hasImagery",
        'snapshot.coverageStatus === "unavailable"',
        "function renderWeatherLiveSummary",
        "function weatherTimelineFrames",
        "function renderWeatherTimeline",
        "function renderWeatherIntersectionMap",
        "function renderWeatherActions",
        "/weather-dashboard",
        "weatherDecisionDashboard.v1",
        "routeRisk",
        "routeTrend",
        "candidateDecision",
        "function renderWeatherDecisionEvidence",
        "Decision / Why / Where / When",
        'data-weather-cwa-map-frame="true"',
        'data-weather-cwa-product="true"',
        'data-weather-cwa-window="true"',
        'data-weather-cwa-timeline="true"',
        'data-weather-cwa-opacity="radar"',
        'data-weather-cwa-opacity="satellite"',
        "function bindWeatherCwaMapFrame",
        "function scheduleWeatherCwaBridgeRetry",
        "function weatherCwaBridgeShouldWait",
        "if (weatherCwaBridgeShouldWait(event.detail))",
        "scoutCwaImageryController",
        'data-weather-status',
        'data-weather-decision-band="true"',
        'data-weather-timeline="true"',
        'data-weather-evidence-timeline="true"',
        'data-weather-evidence-time="true"',
        "evidenceTimeline.value = String(state.weatherTimelineIndex)",
        'data-weather-intersection-map="true"',
        'data-weather-intersection-callout="true"',
        "Canonical Pre-trip Map",
        'data-weather-actions="true"',
        'data-weather-recheck="true"',
        "renderWeatherIntersectionMap(snapshot)",
        "WEATHER_MAP_LAYER_IDS",
        'mode === "weather" && !WEATHER_MAP_LAYER_IDS.includes(layerId)',
        "cache-only",
        "Candidate evidence only.",
        "Weather decision reference",
        "example rules",
        'triggerDashboardConnectedPreparation("operator-refresh", {force: true})',
        "function triggerDashboardConnectedPreparation",
        "function connectedPreparationActivityLabel",
        "preparationInProgress",
        "preparationStillRunning",
        'status: "preparing"',
        'if (weather.status === "preparing") return "loading";',
        'connectedPreparationActivityLabel(preparation.cwaApiRequestAttempted, preparation.status)',
        'connectedPreparationActivityLabel(preparation.externalApiCallsMade, preparation.status)',
        "/connected-preparation",
            "function loadConnectedPreparationStatus",
            'triggerDashboardConnectedPreparation("workspace-operator-refresh"',
        "connectedPreparation",
        "function weatherPercentLabel",
        "function requestAuthorizedRainfallTrend",
        "/rainfall-location-approvals",
        "/rainfall-trend",
        "navigator.geolocation.getCurrentPosition",
        "confirmLocationAccess: true",
        'data-weather-location-trend="true"',
        ):
            assert marker in html
    assert "void loadConnectedPreparationStatus();" in html
    assert 'triggerDashboardConnectedPreparation("dashboard-open")' not in html
    assert 'const pastRainfall = rainfallProducts.find(item => item.gridKind === "qpe_past_1h")' in html
    assert 'const futureRainfall = rainfallProducts.find(item => item.gridKind === "qpf_next_1h")' in html
    assert '"Past 1h QPE"' in html
    assert '"Next 1h QPF"' in html
    assert "no valid route-bbox values" in html
    assert "unknown, not zero" in html
    assert "No rainfall cells cover the route review bbox." not in html

    assert "weatherPercentLabel(features.convectiveCellScore)" in html
    assert "weatherPercentLabel(features.satelliteConvectiveCloudScore)" in html
    assert "weatherPercentLabel(features.confidence)" in html
    assert "weatherNumberLabel(Number(features.convectiveCellScore) * 100" not in html
    assert "weatherNumberLabel(Number(features.satelliteConvectiveCloudScore) * 100" not in html
    assert 'prepareProfile: "mac-workstation"' in html
    assert 'networkMode: "explicit-fetch"' in html
    assert "allowNetworkFetch: true" in html

    weather_page = html.split("function renderWeatherPage", 1)[1].split(
        "function renderNavigationPage", 1
    )[0]
    assert "CHANGE_PLAN" not in weather_page
    assert "13:00" not in weather_page
    assert "CP087" not in weather_page
    assert 'renderMapPanel("weather")' not in weather_page
    assert 'data-weather-field-hero="true"' not in weather_page
    assert "Weather is not a forecast." not in weather_page
    assert "It is a route constraint." not in weather_page
    assert ".weather-field-hero" not in html


def test_dashboard_weather_refresh_runs_server_connected_preparation() -> None:
    html = PAGE.read_text(encoding="utf-8")
    actions = html.split("function renderWeatherActions", 1)[1].split(
        "function renderWeatherExampleRules", 1
    )[0]
    handler = html.split(
        'document.querySelector("[data-weather-recheck]")?.addEventListener', 1
    )[1].split('document.querySelector("[data-debug-retry]")', 1)[0]

    assert 'data-weather-refresh-status="true"' in actions
    assert "更新 CWA 現況" in actions
    assert "正在向 CWA 更新" in actions
    assert "const evidenceFetchedAt = snapshot.preferredRainfall?.fetchedAt" in actions
    assert "目前 workspace 快取更新於" in actions
    assert "const button = event.currentTarget;" in handler
    assert 'triggerDashboardConnectedPreparation("operator-refresh", {force: true})' in handler
    assert 'loadDataForRoute("outdoor-weather", {force: true})' not in handler
    assert "connectedPreparation: state.connectedPreparation || weather.connectedPreparation" in html
    assert "function formatCwaTimestampOr(value, fallback)" in html
    assert 'formatCwaTimestampOr(preparation.completedAt, "not completed")' in html
    assert 'formatCwaTimestampOr(snapshot.preferredRainfall?.validUntil, "unresolved")' in html
    assert 'formatCwaTimestampOr(radarSourceTimestamp, "awaiting frame")' in html
    assert "scheduleConnectedPreparationPolling" in html
    assert "status.completedAt !== priorCompletedAt" in html
    assert "await loadWeatherData();" in html


def test_dashboard_weather_location_action_reports_cached_sampling_result() -> None:
    html = PAGE.read_text(encoding="utf-8")
    location_flow = html.split(
        "function weatherRainfallTrendResultText", 1
    )[1].split("function renderWeatherDecisionEvidence", 1)[0]
    location_panel = html.split(
        'data-weather-location-trend="true"', 1
    )[1].split("</section>", 1)[0]

    assert "以目前位置重算降雨趨勢" in location_panel
    assert 'data-weather-location-mode="cached-sampling"' in location_panel
    assert "不更新 CWA" in location_panel
    assert "trend.sourceTimestamps?.next1hQpf" in location_flow
    assert "trend.currentPosition" in location_flow
    assert "trend.target" in location_flow
    assert "未下載新 CWA" in location_flow
    assert "座標未保存" in location_flow
    assert "rawCoordinatesPersisted=" not in location_flow
    assert "瀏覽器未允許位置存取" in html


def test_dashboard_uses_weather_field_instrument_design_system_across_routes() -> None:
    html = PAGE.read_text(encoding="utf-8")

    assert '<body class="field-instrument-theme">' in html
    for marker in (
        "Field Decision Instrument design system.",
        ".field-instrument-theme .dashboard-shell",
        ".field-instrument-theme .dashboard-sidebar",
        ".field-instrument-theme .topbar",
        ".field-instrument-theme .workspace > *",
        ".field-instrument-theme .panel",
        ".field-instrument-theme .agent-app-shell",
        ".field-instrument-theme .surface-frame-panel",
        ".field-instrument-theme .route-tabs",
        ".field-instrument-theme .table th",
        ".field-instrument-theme .scout-map",
        ".field-instrument-theme .evidence-drawer",
        ".field-instrument-theme input",
        ".field-instrument-theme textarea",
        "@keyframes field-instrument-arrive",
    ):
        assert marker in html

    for color in ("#08100e", "#101a17", "#b7cf63", "#f0ae3b", "#ff6b4a"):
        assert color in html


def test_dashboard_collapses_secondary_evidence_for_four_six_force_routes() -> None:
    html = PAGE.read_text(encoding="utf-8")

    compact_routes = html.split("const COLLAPSIBLE_EVIDENCE_ROUTES", 1)[1].split(
        ");", 1
    )[0]
    for route in (
        "outdoor-permission",
        "outdoor-architecture",
        "outdoor-weather",
        "outdoor-navigation",
    ):
        assert f'"{route}"' in compact_routes

    assert '"outdoor-route-context"' not in compact_routes
    assert '"outdoor-pace-fit"' not in compact_routes
    for marker in (
        "function evidenceDrawerCollapsed(route)",
        'classList.toggle("is-evidence-collapsed", evidenceCollapsed)',
        'data-context-evidence-toggle="true"',
        'aria-controls="dashboardContextEvidenceBody"',
        'aria-expanded="${collapsed ? "false" : "true"}"',
        'id="dashboardContextEvidenceBody"',
        '${collapsed ? "hidden" : ""}',
        "Expand ${title}",
        "Collapse ${title}",
    ):
        assert marker in html


def test_dashboard_uses_strict_project_route_scoped_loading_and_truthful_debug_state() -> None:
    html = PAGE.read_text(encoding="utf-8")

    project_id_candidates = html.split("function pretripDataProjectIds()", 1)[1].split(
        "async function fetchJson", 1
    )[0]
    assert "replace(/_scoutAI$/" not in project_id_candidates
    assert "PRETRIP_DATA_PROJECT_ID" not in project_id_candidates
    assert "return [projectId()]" in project_id_candidates

    for marker in (
        "ROUTE_DATA_SCOPES",
        "loadDataForRoute",
        "loadedDataScopes",
        "debugEndpointStates",
        "DEGRADED",
        'data-debug-retry',
    ):
        assert marker in html

    project_scope = html.split("project: [", 1)[1].split("],", 1)[0]
    assert '"map"' not in project_scope
    assert '"outdoor-navigation"' not in project_scope
    assert "const NAVIGATION_TERRAIN_FETCH_TIMEOUT_MS = 60000;" in html
    assert "{timeoutMs: NAVIGATION_TERRAIN_FETCH_TIMEOUT_MS}" in html


def test_dashboard_map_reuses_pretrip_projection_and_reports_progressive_loading() -> None:
    html = PAGE.read_text(encoding="utf-8")
    pretrip_html = PRETRIP_PAGE.read_text(encoding="utf-8")

    for marker in (
        'id="dashboardMapLoading"',
        'role="status"',
        'aria-live="polite"',
        "if (!scopes.length) return;",
        "function updateDashboardMapLoading",
        "function adoptPretripMapProjectBridge",
        '&mapOnly=1',
        "scoutPretripProjectBridge",
        'frame.dataset.mapOnlyReady = "true"',
        'frame.dataset.mapOnlyReady = "blocked"',
    ):
        assert marker in html

    for marker in (
        "window.scoutPretripProjectBridge = Object.freeze",
        "function publishPretripProjectBridge",
        'publishPretripProjectBridge("loading")',
        'publishPretripProjectBridge("base_ready")',
        'publishPretripProjectBridge("enhanced_ready")',
        'publishPretripProjectBridge("degraded"',
        "function renderProjectView",
        "if (DASHBOARD_MAP_ONLY) return;",
        "Promise.allSettled",
    ):
        assert marker in pretrip_html

    reload_body = pretrip_html.split("async function reloadProjectView()", 1)[1].split(
        "async function loadOsmPbfVectorLayer", 1
    )[0]
    assert reload_body.index("renderProjectView(view)") < reload_body.index(
        "loadCwaRainfallGridOverlay(view)"
    )
    assert reload_body.index('publishPretripProjectBridge("base_ready")') < reload_body.index(
        "Promise.allSettled"
    )


def test_dashboard_primary_information_architecture_and_mobile_shell_contract() -> None:
    html = PAGE.read_text(encoding="utf-8")

    assert html.count("data-nav-primary") == 7
    for label in (
        "Overview",
        "Plan Trip",
        "Map & Evidence",
        "Exploring for Six Axis",
        "Safety / Emergency",
        "Assistant",
        "System",
    ):
        assert label in html

    nav_html = html.split('<nav class="nav"', 1)[1].split("</nav>", 1)[0]
    assert "Team & Pace" not in nav_html
    assert "Safety Decisions" not in nav_html
    assert "Labs / Preview" not in nav_html

    six_force_nav = nav_html.split(
        'data-nav-group="outdoor-six-forces"', 1
    )[1].split('data-nav-primary data-route="emergency"', 1)[0]
    expected_six_force_routes = (
        "outdoor-route-context",
        "outdoor-pace-fit",
        "outdoor-permission",
        "outdoor-architecture",
        "outdoor-weather",
        "outdoor-navigation",
    )
    assert six_force_nav.count('data-six-force-route="true"') == 6
    route_positions = [
        six_force_nav.index(
            f'data-six-force-route="true" data-route="{route}"'
        )
        for route in expected_six_force_routes
    ]
    assert route_positions == sorted(route_positions)
    assert "Pace Dashboard" in six_force_nav
    assert "Body Index" in six_force_nav
    assert "Emergency UI" not in six_force_nav
    assert "function openNavigationAncestors(button)" in html
    assert "if (active) openNavigationAncestors(button);" in html

    assert 'data-route-truth="live"' in html
    assert 'data-route-truth="partial"' in html
    assert 'data-route-truth="preview"' in html
    assert 'id="dashboardNavToggle"' in html
    assert 'aria-controls="dashboardSidebar"' in html
    assert "bindMobileNavigation" in html
    assert "70dvh" in html
    assert "env(safe-area-inset-bottom)" in html


def test_dashboard_p0_p2_review_regressions_are_fail_closed() -> None:
    html = PAGE.read_text(encoding="utf-8")
    pretrip_html = PRETRIP_PAGE.read_text(encoding="utf-8")
    smoke = SMOKE_TOOL.read_text(encoding="utf-8")

    assert 'if (snapshot.status === "unavailable") return "unavailable";' in html
    assert "dataScopeErrors" in html
    assert "loadedDataScopes.add(scope);" in html.split(
        "async function loadDataScope", 1
    )[1].split("async function performDataScope", 1)[0].split(".then", 1)[1]
    assert 'if (nextHref === window.location.href) {' in html
    assert "window.location.reload();" in html
    assert "window.location.replace(nextHref);" in html
    assert "sidebar.inert = !open" in html
    assert 'sidebar.setAttribute("aria-hidden", open ? "false" : "true")' in html

    overlay_loader = pretrip_html.split(
        "async function loadCwaRainfallGridOverlay", 1
    )[1].split("function bindCwaWeatherImageryControls", 1)[0]
    assert 'grid_overlay_status: overlay.status' in overlay_loader
    assert 'overlay.status === "ready" && gridCells.length ? "ready" : "no_coverage"' not in overlay_loader

    assert "/admin/dashboard?projectId=chilai_nanhua_day1#map" in smoke
    assert 'replace(\n      "/projects/chilai_nanhua_day1_scoutAI"' not in smoke


def test_dashboard_trip_intake_validation_is_server_verified_and_non_mutating(
    tmp_path: Path,
) -> None:
    client = TestClient(create_admin_app())
    valid_gpx = tmp_path / "valid.gpx"
    valid_gpx.write_text(
        """<?xml version="1.0" encoding="UTF-8"?>
<gpx version="1.1" creator="dashboard-test" xmlns="http://www.topografix.com/GPX/1/1">
  <trk><name>synthetic</name><trkseg>
    <trkpt lat="23.0" lon="121.0"><ele>100</ele></trkpt>
    <trkpt lat="23.001" lon="121.001"><ele>110</ele></trkpt>
  </trkseg></trk>
</gpx>
""",
        encoding="utf-8",
    )

    valid = client.post(
        "/admin/dashboard/trip-intake/validate",
        json={"project_id": "synthetic_trip_scoutAI", "golden_route_gpx": str(valid_gpx)},
    )
    assert valid.status_code == 200, valid.text
    payload = valid.json()
    assert payload["status"] == "validated"
    assert payload["validation_stage"] == "gpx_parsed"
    assert payload["point_count"] == 2
    assert payload["boundary"] == {
        "filesystem_mutation_performed": False,
        "runtime_safety_truth": False,
        "raw_gpx_embedded": False,
        "coordinates_embedded": False,
    }
    assert str(valid_gpx) not in valid.text
    assert "23.0" not in valid.text
    assert "121.0" not in valid.text

    cases = [
        (tmp_path / "missing.gpx", "File not found"),
        (tmp_path, "regular file"),
    ]
    malformed = tmp_path / "malformed.gpx"
    malformed.write_text("<gpx><trk>", encoding="utf-8")
    cases.append((malformed, "valid GPX"))
    not_gpx = tmp_path / "not-gpx.txt"
    not_gpx.write_text("plain text", encoding="utf-8")
    cases.append((not_gpx, ".gpx"))
    unreadable = tmp_path / "unreadable.gpx"
    unreadable.write_text(valid_gpx.read_text(encoding="utf-8"), encoding="utf-8")
    unreadable.chmod(0)
    cases.append((unreadable, "readable"))

    try:
        for source, expected_detail in cases:
            response = client.post(
                "/admin/dashboard/trip-intake/validate",
                json={
                    "project_id": "synthetic_trip_scoutAI",
                    "golden_route_gpx": str(source),
                },
            )
            assert response.status_code == 422, response.text
            assert expected_detail.lower() in response.json()["detail"].lower()
    finally:
        unreadable.chmod(0o600)


def test_dashboard_joint_review_truth_semantics_and_pagination_contract() -> None:
    html = PAGE.read_text(encoding="utf-8")

    assert 'data-route="agent" data-route-truth="partial"' in html
    assert "const ROUTE_TRUTH = Object.freeze" in html
    for route in (
        "home",
        "features-workspace",
        "features-import-new-trip",
        "features-country-material-pool",
        "map",
        "timeline",
        "features-lbs",
        "outdoor-route-context",
        "outdoor-pace-fit",
        "outdoor-pace-fit-body-index",
        "emergency",
        "outdoor-weather",
        "agent",
        "surface-debug",
        "debug",
        "settings",
        "diagnostic",
        "outdoor-permission",
        "observer",
        "outdoor-architecture",
        "outdoor-navigation",
    ):
        assert f'"{route}": Object.freeze' in html

    for field in ("surface", "data", "action", "verification", "provenance"):
        assert f'data-truth-field="{field}"' in html
    assert "function resolveRouteTruth(route)" in html
    assert "function renderTruthStrip(route)" in html
    assert "function deriveAssistantReadiness" in html
    assert "window.scoutDashboardTruthContracts" in html
    assert "assistantReadiness: (status) => deriveAssistantReadiness(status)" in html
    assert "connection not checked" in html.lower()
    assert "repository not ready" in html.lower()
    assert 'id="agentComposerStatus"' in html
    assert "Enter a question before sending." in html
    assert "state.agentBusy || !questionAvailable" in html

    pace = html.split("function renderPaceFitPage", 1)[1].split(
        "function renderPaceFitBodyIndexPage", 1
    )[0]
    assert "Pace Parameters" in pace
    assert "Read-only preview" in pace
    assert "Pace Controls" not in pace
    assert 'role="list"' in pace
    assert 'role="listitem"' in pace

    assert "function debugEventProvenance" in html
    provenance_function = html.split("function debugEventProvenance", 1)[1].split(
        "function debugProvenanceSummary", 1
    )[0]
    assert "event.event_provenance" in provenance_function
    assert "Unknown" in provenance_function
    assert "haystack" not in provenance_function
    assert "event.summary" not in provenance_function
    assert "event.payload" not in provenance_function
    assert "Fixture replay" in html
    assert "Smoke test" in html
    assert "Event provenance" in html
    assert "Transport" in html

    assert "const EVIDENCE_PAGE_SIZE = 100;" in html
    assert "function paginateEvidenceGroup" in html
    assert "function evidenceGroupPageForSource" in html
    assert "function evidenceGroupPage(context, tabId, groupTitle)" in html
    assert "function setEvidenceGroupPage(context, tabId, groupTitle, page)" in html
    assert "function evidenceOpenGroup(context, tabId)" in html
    assert "function setEvidenceOpenGroup(context, tabId, groupTitle)" in html
    assert 'data-evidence-page-action="previous"' in html
    assert 'data-evidence-page-action="next"' in html
    assert "data-evidence-page-group=" in html
    assert "data-evidence-page-current=" in html
    assert 'aria-label="${escapeHtml(groupTitle)} pagination"' in html
    assert "function paginateEvidenceGroups" not in html
    assert "renderEvidencePagination(pagination" not in html
    assert "Evidence exists in this category but is on another page." not in html
    assert (
        "activeGroups.map((group, index) => renderPretripEvidenceGroup(" in html
    )
    assert 'data-evidence-group-toggle="true"' in html

    group_open_policy = html.split(
        "function pretripEvidenceGroupOpen", 1
    )[1].split("function pretripEvidenceGroups", 1)[0]
    assert "return false;" in group_open_policy
    assert "index < 2" not in group_open_policy

    pagination = html.split(
        "function paginateEvidenceGroup", 1
    )[1].split("function evidenceGroupPageForSource", 1)[0]
    assert "const items = asArray(group.items);" in pagination
    assert "items: items.slice(startIndex, endIndex)" in pagination
    assert "loadedItemCount: items.length" in pagination


def test_dashboard_joint_review_information_architecture_and_qa_contract() -> None:
    html = PAGE.read_text(encoding="utf-8")

    for copy in (
        "Clone and prepare workspace",
        "Record transfer request",
        "Record package request",
        "Record restore request",
        "Request deletion review",
        "Preview Import",
        "Create Workspace",
        "Clone creates a new target with one clean GPX import",
        "32 canonical layers",
        "completed-track is after-action only",
        "Remaining Mission Projection",
        "Current decision",
        "Operational workbench",
        "Technical Prototype",
        "Reference",
        "Candidate-only",
        "Current Decision Brief",
    ):
        assert copy in html

    assert 'id="settingsStatus"' in html
    assert 'role="status"' in html
    assert "function validateDashboardSettings" in html
    assert "function saveDashboardSettings" in html
    assert "Settings were not saved" in html
    assert "saveState.reloadPending" in html
    assert "Boolean(changed.length)" in html
    assert 'if (nextHref === window.location.href) {' in html
    assert "window.location.reload();" in html
    assert "window.location.replace(nextHref);" in html
    assert 'truth.mode = readiness.level === "ready" ? "Operational" : "Not operational";' in html
    assert "const loadingScopes = requiredScopes.filter" in html
    assert 'truth.mode = "Loading";' in html
    assert "function bindRovingTablists" in html
    assert "pendingTabFocus" in html
    assert "focus({preventScroll: true})" in html
    assert 'id="agentAskButton" aria-describedby="agentComposerStatus"' in html
    assert 'data-import-trip-action="preview" aria-describedby="importTripStatus"' in html
    assert 'data-import-trip-action="create" aria-describedby="importTripStatus"' in html
    assert "Hide embedded surface" in html
    assert 'id="surfaceFrameExit"' in html
    assert 'focus({preventScroll: true})' in html
    assert '["Enter", " ", "Spacebar"].includes(event.key)' in html
    assert "ArrowRight" in html
    assert "ArrowLeft" in html
    assert "grid-template-columns: 1fr;" in html.split(
        "@media (max-width: 1120px)", 1
    )[1].split("@media (max-width: 620px)", 1)[0]
    assert ".force-row.overview-primary-row" in html.split(
        "@media (max-width: 1120px)", 1
    )[1].split("@media (max-width: 620px)", 1)[0]

    home = html.split("function renderHomePage()", 1)[1].split(
        "function renderTimelinePanel()", 1
    )[0]
    ordered_overview_markers = (
        'data-overview-step="workspace-identity"',
        'data-overview-step="current-decision"',
        'data-overview-step="blocking-truth"',
        'data-overview-step="next-action"',
        'data-overview-secondary="verification"',
    )
    marker_positions = [home.index(marker) for marker in ordered_overview_markers]
    assert marker_positions == sorted(marker_positions)
    primary_overview = home.split('data-overview-secondary="verification"', 1)[0]
    assert 'data-route="surface-admin"' not in primary_overview
    assert 'data-route="surface-debug"' not in primary_overview


def test_dashboard_truth_contracts_cover_assistant_matrix_and_settings_failure() -> None:
    html = PAGE.read_text(encoding="utf-8")
    script = html.split("<script>", 1)[1].split("</script>", 1)[0]
    node_program = f"""
const dashboardScript = {json.dumps(script)};
const elements = {{
  apiBaseInput: {{value: "http://127.0.0.1:9099"}},
  projectInput: {{value: "synthetic_settings_project"}},
  reloadSettings: {{disabled: false}},
  settingsStatus: {{textContent: "", dataset: {{}}}},
}};
const documentStub = {{
  addEventListener() {{}},
  getElementById(id) {{ return elements[id] || null; }},
  querySelector() {{ return null; }},
  querySelectorAll() {{ return []; }},
}};
const windowStub = {{
  location: {{href: "http://127.0.0.1:9099/admin/dashboard", search: ""}},
  CSS: {{escape(value) {{ return String(value); }}}},
  requestAnimationFrame(callback) {{ callback(); }},
}};
const storage = {{
  values: {{}},
  failWrites: true,
  getItem(key) {{ return this.values[key] || null; }},
  setItem(key, value) {{
    if (this.failWrites) throw new Error("synthetic storage failure");
    this.values[key] = String(value);
  }},
}};
const contracts = new Function(
  "document", "window", "localStorage",
  dashboardScript + "; return {{deriveAssistantReadiness, dashboardWeatherDerivedStatus, validateDashboardSettings, saveDashboardSettings}};"
)(documentStub, windowStub, storage);
const assistantCases = {{
  checking: contracts.deriveAssistantReadiness({{checked: false}}),
  not_checked: contracts.deriveAssistantReadiness({{checked: true, raw: {{startup_connection_status: "not_checked", assistant_workflow: {{repository_readiness_ok: false}}}}}}),
  ready: contracts.deriveAssistantReadiness({{checked: true, raw: {{startup_connection_status: "connected:cloud", assistant_workflow: {{repository_readiness_ok: true}}}}}}),
  degraded: contracts.deriveAssistantReadiness({{checked: true, raw: {{startup_connection_status: "connected:cloud", assistant_workflow: {{repository_readiness_ok: false}}}}}}),
  failed: contracts.deriveAssistantReadiness({{checked: true, raw: {{startup_connection_status: "failed:TimeoutError"}}}}),
  unavailable: contracts.deriveAssistantReadiness({{checked: true, provider: "unavailable", error: "synthetic endpoint failure"}}),
}};
const invalid = contracts.validateDashboardSettings("ftp://example.test", "bad project id");
const weatherCases = {{
  fresh: contracts.dashboardWeatherDerivedStatus({{
    status: "ready",
    rainfall: {{status: "fresh", products: [{{gridKind: "qpf_next_1h", availableCellCount: 12, freshness: {{status: "fresh"}}}}]}},
    imagery: {{status: "ready", childOverlays: {{radar: {{latestFrameId: "radar-1", frames: [{{frameId: "radar-1"}}]}}}}}},
  }}, {{}}),
  failed: contracts.dashboardWeatherDerivedStatus({{status: "error"}}, {{}}),
  stale: contracts.dashboardWeatherDerivedStatus({{
    status: "ready",
    rainfall: {{products: [{{gridKind: "qpf_next_1h", availableCellCount: 12, freshness: {{status: "stale_data"}}}}]}},
    imagery: {{status: "ready", childOverlays: {{radar: {{frames: []}}}}}},
  }}, {{}}),
  no_coverage: contracts.dashboardWeatherDerivedStatus({{
    status: "ready",
    rainfall: {{products: [{{gridKind: "qpf_next_1h", availableCellCount: 0, freshness: {{status: "fresh"}}}}]}},
    imagery: {{status: "ready", childOverlays: {{radar: {{frames: []}}}}}},
  }}, {{}}),
}};
const failedSave = contracts.saveDashboardSettings();
const failedReceipt = {{
  result: failedSave,
  text: elements.settingsStatus.textContent,
  tone: elements.settingsStatus.dataset.tone,
  reloadDisabled: elements.reloadSettings.disabled,
}};
storage.failWrites = false;
const successfulSave = contracts.saveDashboardSettings();
const successReceipt = {{
  result: successfulSave,
  text: elements.settingsStatus.textContent,
  tone: elements.settingsStatus.dataset.tone,
  reloadDisabled: elements.reloadSettings.disabled,
}};
process.stdout.write(JSON.stringify({{assistantCases, weatherCases, invalid, failedReceipt, successReceipt}}));
"""
    result = subprocess.run(
        ["node"],
        input=node_program,
        text=True,
        capture_output=True,
        check=True,
    )
    payload = json.loads(result.stdout)

    assert {key: value["level"] for key, value in payload["assistantCases"].items()} == {
        "checking": "checking",
        "not_checked": "not_checked",
        "ready": "ready",
        "degraded": "degraded",
        "failed": "unavailable",
        "unavailable": "unavailable",
    }
    assert {key: value["tone"] for key, value in payload["assistantCases"].items()} == {
        "checking": "warn",
        "not_checked": "warn",
        "ready": "ok",
        "degraded": "warn",
        "failed": "bad",
        "unavailable": "bad",
    }
    assert payload["invalid"]["ok"] is False
    assert payload["weatherCases"] == {
        "fresh": "ready",
        "failed": "error",
        "stale": "stale_data",
        "no_coverage": "no_coverage",
    }
    assert payload["failedReceipt"] == {
        "result": False,
        "text": "Settings were not saved: browser storage failed (synthetic storage failure).",
        "tone": "bad",
        "reloadDisabled": True,
    }
    assert payload["successReceipt"]["result"] is True
    assert payload["successReceipt"]["tone"] == "ok"
    assert payload["successReceipt"]["reloadDisabled"] is False


def test_dashboard_diagnostic_page_runs_38_read_only_checks() -> None:
    html = PAGE.read_text(encoding="utf-8")

    settings_nav = (
        '<button class="nav-item" type="button" data-route="settings" '
        'data-route-truth="live"'
    )
    diagnostic_nav = (
        '<button class="nav-item" type="button" data-route="diagnostic" '
        'data-route-truth="live"'
    )
    assert settings_nav in html
    assert diagnostic_nav in html
    assert html.index(diagnostic_nav) > html.index(settings_nav)
    assert '"diagnostic": Object.freeze' in html
    assert 'diagnostic: ["Diagnostic", "38 read-only Dashboard checks"]' in html
    assert 'if (route === "diagnostic") return renderDiagnosticPage();' in html

    case_source = html.split(
        "const DASHBOARD_DIAGNOSTIC_CASES = Object.freeze([", 1
    )[1].split("]);", 1)[0]
    for index in range(1, 39):
        assert f'id: "DASH-{index:03d}"' in case_source
    assert case_source.count('id: "DASH-') == 38
    assert "postJson(" not in case_source

    for marker in (
        "async function diagnosticCheck026()",
        "async function diagnosticCheck027()",
        "async function diagnosticCheck028()",
        "async function diagnosticCheck029()",
        "async function diagnosticCheck030()",
        "async function diagnosticCheck031()",
        "async function diagnosticCheck032()",
        "async function diagnosticCheck033()",
        "async function diagnosticCheck034()",
        "async function diagnosticCheck035()",
        "async function diagnosticCheck036()",
        "async function diagnosticCheck037()",
        "async function diagnosticCheck038()",
        "所有 Dashboard 地圖 evidence hover hint",
        "所有 Dashboard 地圖框選縮放與鍵盤平移",
        "所有 Dashboard 地圖圖磚、向量與單圖例外政策",
        "所有 Dashboard 地圖基本 Zoom、Pan 與 Fit",
        "Evidence 是否有計數為 0 的類別",
        "Contextual Permission 專案範圍與只讀 API",
        "Contextual Permission Workbench 與行動版檢視",
        "Immutable Baseline、Forward Projection 與調整政策",
        "Safety / Emergency 專屬決策與權限邊界",
        "Contextual Permission Evidence lineage 與隱私邊界",
        "Candidate Simulation 明確觸發與 no-write contract",
        "Navigation、Architecture、Weather 動態圖磚倍率切換",
        "Navigation MapLibre 2D/3D 鏡頭持久化",
        "DASHBOARD_MAP_APPROVED_SINGLE_IMAGE_THEMES",
        "const DASHBOARD_MAP_SURFACES = Object.freeze([",
        "diagnosticMapSurfaceSources",
        "function diagnosticZeroCountEvidenceCategories(",
        "function diagnosticRudyTileMatrixFromUrl(",
        "function diagnosticDynamicRudyTileContract(",
        "function diagnosticPermissionProjection(",
        "function diagnosticPermissionRoot(",
        "function diagnosticRequireNoAuthority(",
        ".filter(group => Number(group.count) === 0)",
        ".filter(item => Number(item.count) === 0)",
        'group.zeroReasonCode || "fixture_or_projection_omission"',
        '"source_checked_no_matches"',
        '"source_unavailable"',
        '"prepared_no_candidates"',
        'const reason = ["capability_timeline", "rest_intervals"].includes(item.category_id)',
        "Evidence categories count=0 with typed reasons:",
    ):
        assert marker in html

    surface_source = html.split(
        "const DASHBOARD_MAP_SURFACES = Object.freeze([", 1
    )[1].split("]);", 1)[0]
    for surface_id in (
        "overview-map",
        "lbs-map",
        "permission-map",
        "emergency-review-map",
        "map",
        "weather-map",
        "navigation-map",
        "architecture-map",
        "pace-fit-map",
    ):
        assert f'id: "{surface_id}"' in surface_source
    assert surface_source.count("{id:") == 9

    for marker in (
        "function renderDiagnosticPage()",
        "function renderDiagnosticCase(",
        "async function runDashboardDiagnostic(",
        "async function runAllDashboardDiagnostics()",
        "function bindDiagnosticControls()",
        'data-diagnostic-action="all"',
        'data-diagnostic-action="retest"',
        'data-diagnostic-status="running"',
        'data-diagnostic-status="passed"',
        'data-diagnostic-status="warning"',
        'data-diagnostic-status="failed"',
        "測試中",
        "測試通過",
        "測試提醒",
        "測試失敗",
        "重新測試",
        "Diag all",
        "Read-only diagnostics",
        "does not replace the full acceptance checklist",
        "window.scoutDashboardDiagnostics",
    ):
        assert marker in html

    runner = html.split(
        "async function runDashboardDiagnostic(", 1
    )[1].split("async function runAllDashboardDiagnostics()", 1)[0]
    assert "postJson(" not in runner
    assert 'status: "running"' in runner
    assert 'status: warning ? "warning" : "passed"' in runner
    assert 'status: "failed"' in runner
    assert "performance.now()" in runner

    check_030 = html.split(
        "async function diagnosticCheck030()", 1
    )[1].split("async function diagnosticCheck031()", 1)[0]
    assert "unexplainedZeroCountCategories" not in check_030
    assert "return diagnosticWarning(" in check_030


def test_dashboard_diagnostic_classifies_expected_runtime_gaps_without_false_reds() -> None:
    html = PAGE.read_text(encoding="utf-8")

    check_002 = html.split(
        "async function diagnosticCheck002()", 1
    )[1].split("async function diagnosticCheck003()", 1)[0]
    assert '"runtime-audit"' in check_002

    check_018 = html.split(
        "async function diagnosticCheck018()", 1
    )[1].split("async function diagnosticCheck019()", 1)[0]
    assert "Route Context is recorded as deferred / not implemented" in check_018
    assert "return diagnosticWarning(" in check_018

    check_019 = html.split(
        "async function diagnosticCheck019()", 1
    )[1].split("async function diagnosticCheck020()", 1)[0]
    assert "records.length === 0" in check_019
    assert "return diagnosticWarning(" in check_019

    check_025 = html.split(
        "async function diagnosticCheck025()", 1
    )[1].split("function diagnosticSourceText(", 1)[0]
    assert 'data-navigation-maplibre-shell="2d"' in check_025
    assert 'data-navigation-maplibre-shell="3d"' in check_025
    assert 'Boolean(map || mapLibre2d)' in check_025
    assert "MapLibre 2D primary terrain map rendered" in check_025
    assert "Navigation Map Literacy Checklist is missing" not in check_025

    permission_ready = html.split(
        "function diagnosticRequirePermissionReady(", 1
    )[1].split("function diagnosticPermissionRoot(", 1)[0]
    assert '["ready", "degraded"].includes(projection?.status)' in permission_ready

    for case_id, next_case_id in (("032", "033"), ("033", "034"), ("035", "036")):
        check = html.split(
            f"async function diagnosticCheck{case_id}()", 1
        )[1].split(f"async function diagnosticCheck{next_case_id}()", 1)[0]
        assert "return diagnosticWarning(" in check


def test_dashboard_diagnostic_gives_known_slow_read_endpoints_bounded_headroom() -> None:
    html = PAGE.read_text(encoding="utf-8")

    assert (
        "function diagnosticWorkspaceContext() {\n"
        "      return diagnosticJson(`/admin/dashboard/workspaces/${encodeURIComponent(projectId())}`, 180000);"
    ) in html
    check_001 = html.split(
        "async function diagnosticCheck001()", 1
    )[1].split("async function diagnosticCheck002()", 1)[0]
    check_010 = html.split(
        "async function diagnosticCheck010()", 1
    )[1].split("async function diagnosticCheck011()", 1)[0]
    check_012 = html.split(
        "async function diagnosticCheck012()", 1
    )[1].split("async function diagnosticCheck013()", 1)[0]

    assert "diagnosticJson(`${projectPath}/debug-projection`, 180000)" in check_001
    assert (
        "diagnosticJson(`/admin/pretrip/projects/${project}/debug-projection`, 180000)"
        in check_010
    )
    assert "operation-requests`, 180000)" in check_012


def test_dashboard_diagnostic_checks_probe_runtime_data_and_rendered_behavior() -> None:
    html = PAGE.read_text(encoding="utf-8")
    browser_smoke = (
        ROOT / "tools" / "dashboard_diagnostic_browser_smoke.js"
    ).read_text(encoding="utf-8")
    diagnostic_source = html.split(
        "function diagnosticStatusLabel(", 1
    )[1].split("function validateDashboardSettings(", 1)[0]

    for helper in (
        "function diagnosticMarkupRoot(",
        "function diagnosticRouteMarkup(",
        "function diagnosticLayerControlIds(",
        "async function diagnosticFetchStatus(",
        "function diagnosticExerciseSharedMapController(",
        "function diagnosticPermissionProjection(",
        "function diagnosticPermissionRoot(",
        "function diagnosticRequireNoAuthority(",
    ):
        assert helper in diagnostic_source

    for endpoint in (
        "/debug-projection-events",
        "/debug-projection",
        "/weather-dashboard",
        "/navigation-terrain-intelligence",
        "/connected-preparation",
        "/contextual-permission-dashboard",
    ):
        assert endpoint in diagnostic_source

    assert "diagnosticFetchStatus(" in diagnostic_source
    assert "__diagnostic_missing_workspace__" in diagnostic_source
    assert "Expected 31 pre-trip layer controls" in diagnostic_source
    assert "diagnosticExerciseSharedMapController()" in diagnostic_source
    assert "paginateEvidenceGroup(pagedGroup, 2" in diagnostic_source
    assert "renderPaceFitPage(force)" in diagnostic_source
    assert 'renderOutdoorPage("outdoor-architecture")' in diagnostic_source
    assert 'renderOutdoorPage("outdoor-navigation")' in diagnostic_source

    for marker in (
        "async function diagnosticCheck031()",
        "async function diagnosticCheck032()",
        "async function diagnosticCheck033()",
        "async function diagnosticCheck034()",
        "async function diagnosticCheck035()",
        "async function diagnosticCheck036()",
        "async function diagnosticCheck037()",
        "async function diagnosticCheck038()",
        'artifact_kind === "contextual_permission_dashboard_projection"',
        'schema_version === "contextualPermissionDashboard.v1"',
        'data-contextual-permission-workbench="ready"',
        'requiredPolicy of ["auto_reduce", "protected_floor", "review_only"]',
        'permission_page_can_decide === false',
        'cause.source_kind !== "human_operation"',
        "Inputs changed · not evaluated.",
        "Current Decision not replaced",
        "NAVIGATION_RUDY_TILE_SOURCE.maxZoom",
        "firstMatrix > initialMatrix",
        "NAVIGATION_RUDY_TILE_SOURCE.preparedMaxZoom + 1",
        "request URL/TILEMATRIX contract crosses prepared Z14",
        "definition.initialMaxZoom + Math.ceil(Math.log2(Math.max(1, state.zoom)))",
        "navigationTerrainMapLibreStoredCamera",
        "rememberNavigationTerrainMapLibreCamera",
        "changedProjection === null",
        "2D Z13.75 · 3D Z17",
    ):
        assert marker in diagnostic_source

    check_010 = diagnostic_source.split(
        "async function diagnosticCheck010()", 1
    )[1].split("async function diagnosticCheck011()", 1)[0]
    assert 'diagnosticJson("/debug/state")' not in check_010
    assert 'diagnosticJson("/debug/messages")' not in check_010
    assert "/debug-projection-events" in check_010
    assert "/debug-projection" in check_010

    check_020 = diagnostic_source.split(
        "async function diagnosticCheck020()", 1
    )[1].split("async function diagnosticCheck021()", 1)[0]
    assert "Function.prototype.toString.call(renderPaceFitPage)" not in check_020
    assert "() => renderPaceFitPage(force)" in check_020

    for case_id in (
        "DASH-009",
        "DASH-018",
        "DASH-019",
        "DASH-030",
        "DASH-032",
        "DASH-033",
        "DASH-035",
    ):
        assert f'"{case_id}"' in browser_smoke
    assert "const expectedDiagnosticCount = 38" in browser_smoke
    assert '"DASH-037"' in browser_smoke
    assert '"DASH-038"' in browser_smoke
    assert "async function inspectNavigationMapLibreCameraPersistence(" in browser_smoke
    assert "async function inspectNavigationMapMarkerFocus(" in browser_smoke
    assert "navigationCameraPersistence" in browser_smoke
    assert "navigationMapMarkerFocus" in browser_smoke
    assert "SCOUT_DIAGNOSTIC_CAMERA_ONLY" in browser_smoke
    assert '"camera-persistence-only"' in browser_smoke
    assert 'cameraPersistenceCase: snapshot.results["DASH-038"]' in browser_smoke
    assert "function tileMatrixFromUrl(" in browser_smoke
    assert "dynamicTileMatrix" in browser_smoke
    assert "networkTileMatrices" in browser_smoke
    assert "firstActiveMatrix" in browser_smoke
    assert "function advancePastPreparedTileMatrix(" in browser_smoke
    assert "function readNativeRudyTileCoverage(" in browser_smoke
    assert "viewportCoverage: highTileCoverage" in browser_smoke
    assert "coveredRatio >= 0.99" in browser_smoke
    assert "if (!dynamicTilesOnly) {" in browser_smoke
    assert "let snapshot = {" in browser_smoke
    assert "activeMatrix: highTileState.matrix" in browser_smoke
    assert "networkTileMatrices.includes(surface.targetMatrix)" in browser_smoke
    assert "dynamicTileFailures" in browser_smoke
    assert "preparedMatrix: 14, targetMatrix: 15" in browser_smoke
    assert '"emergency-review-map"' in browser_smoke
    assert 'includes("9 Dashboard maps")' in browser_smoke
    assert "dataDependentDiagnosticIds" in browser_smoke
    assert "implementation check failed" in browser_smoke
    assert r"\bis not defined\b|ReferenceError|TypeError:" in browser_smoke


def test_navigation_maplibre_camera_fail_case_and_diagnostic_gate_are_documented() -> None:
    failure_log = (ROOT / "docs" / "admin" / "scout-dashboard-v0.1.md").read_text(
        encoding="utf-8"
    )
    checklist = (
        ROOT / "docs" / "admin" / "scout-dashboard-100-item-functional-verification-checklist.md"
    ).read_text(encoding="utf-8")

    for marker in (
        "DASH-MAP-REG-003",
        "Navigation 2D/3D camera reset after MapLibre interaction",
        "中心同步、尺度獨立",
        "候選點、lens、Evidence、垂直誇張或 2D／3D／Split",
        "Only explicit Fit / Reset may reset the corresponding camera",
        "test_navigation_maplibre_preserves_independent_cameras_across_rerenders",
    ):
        assert marker in failure_log

    for marker in (
        "目前版本：38 / 100",
        "DASH-001～DASH-038",
        "### DASH-038 Navigation MapLibre 2D/3D 鏡頭持久化",
        "DASH-MAP-REG-003",
        "下一個可用編號為 `DASH-039`",
    ):
        assert marker in checklist


def test_dashboard_recommended_local_startup_uses_available_python_path() -> None:
    dashboard_doc = (ROOT / "docs" / "admin" / "scout-dashboard-v0.1.md").read_text(
        encoding="utf-8"
    )
    runbook = (
        ROOT / "docs" / "specs" / "scout-pretrip-full-preparation-runbook.md"
    ).read_text(encoding="utf-8")
    recommended = dashboard_doc.split("Recommended local startup:", 1)[1].split(
        "Required checks before providing a Dashboard URL:", 1
    )[0]
    binding_check = runbook.split("the Dashboard factory with the workspace parent root:", 1)[1].split(
        "Verify the binding before opening the Dashboard:", 1
    )[0]

    for startup in (recommended, binding_check):
        assert "PYTHONPATH=src" in startup
        assert "python3 -m uvicorn" in startup
        assert "admin_api:create_dashboard_app" in startup
        assert "./venv/bin/python" not in startup


def test_dashboard_route_context_variants_index_uses_canonical_file_query_links() -> None:
    source = (ROOT / "tools" / "scout_ai_route_context_briefing_variants.py").read_text(
        encoding="utf-8"
    )

    assert "def _variant_file_href" in source
    assert 'f"?ref={quote(ref, safe=\'\')}"' in source
    assert '_variant_file_href(item["relative_ref"])' in source
    assert '_variant_file_href("route_context_variant_comparison.md")' in source
    assert '_variant_file_href("route_context_variant_comparison.json")' in source


def test_dashboard_approved_qualification_visual_repairs_are_explicit() -> None:
    html = PAGE.read_text(encoding="utf-8")

    force_row_rule = html.split(".force-row {", 1)[1].split("}", 1)[0]
    force_button_rule = html.split(".force-row button {", 1)[1].split("}", 1)[0]
    assert "minmax(0" in force_row_rule
    assert "min-width: 0" in force_button_rule
    assert "white-space: normal" in force_button_rule

    weather_label_rule = html.split(".weather-layer-control strong {", 1)[1].split(
        "}", 1
    )[0]
    body_label_rule = html.split(".body-index-trend-labels span {", 1)[1].split(
        "}", 1
    )[0]
    debug_pill_rule = html.split(".debug-pill {", 1)[1].split("}", 1)[0]
    assert "white-space: normal" in weather_label_rule
    assert "overflow-wrap: anywhere" in weather_label_rule
    assert "white-space: normal" in body_label_rule
    assert "text-overflow: clip" in debug_pill_rule
    assert "overflow-wrap: anywhere" in debug_pill_rule

    mobile_nav_rule = html.split("/* qualification-mobile-nav-scroll */", 1)[1].split(
        "}", 1
    )[0]
    living_mobile_rule = html.split(
        "/* qualification-living-mobile-header */", 1
    )[1].split("}", 1)[0]
    architecture_lens_rule = html.split(
        "/* qualification-architecture-lens-flush-sticky */", 1
    )[1].split("}", 1)[0]
    assert "display: block" in mobile_nav_rule
    assert "min-height: 0" in mobile_nav_rule
    assert "overflow-y: auto" in mobile_nav_rule
    assert ".nav-section:not([open]) > .nav-subtree" in html
    assert "flex-direction: column" in living_mobile_rule
    assert "position: sticky" in architecture_lens_rule
    assert "top: var(--architecture-sticky-flush-offset" in architecture_lens_rule
    assert "--architecture-sticky-flush-offset: -18px" in html
    assert "--architecture-sticky-flush-offset: -12px" in html
    assert "qualification-architecture-sticky-containment" not in html
    architecture_rerender_rule = html.split(
        "/* qualification-architecture-no-rerender-shift */", 1
    )[1].split("}", 1)[0]
    assert "animation: none" in architecture_rerender_rule

    debug_table_rule = html.split(".debug-table {", 1)[1].split("}", 1)[0]
    debug_table_wrap_rule = html.split(".debug-table-wrap {", 1)[1].split("}", 1)[0]
    assert "min-width: 640px" in debug_table_rule
    assert "overflow: auto" in debug_table_wrap_rule
    assert "qualification-debug-table-mobile-readable" not in html

    render_source = html.split("function render() {", 1)[1].split(
        "function renderOverview", 1
    )[0]
    assert "hideDashboardMapHint();" in render_source
    assert 'data-navigation-basemap-layer="rudy-twmap"' in html
    assert "pointer-events: bounding-box" in html
    assert "qualification-six-axis-tabs-visible" in html
    assert "qualification-mobile-nav-scroll" in html
    assert "qualification-architecture-lens-flush-sticky" in html


def test_dashboard_q0056_navigation_hints_are_fixed_and_weather_hints_remain() -> None:
    html = PAGE.read_text(encoding="utf-8")
    navigation_host = html.split(
        "function renderNavigationTerrainMapLibreHost", 1
    )[1].split("function renderNavigationTerrainReviewWorkbench", 1)[0]
    navigation_workbench = html.split(
        "function renderNavigationTerrainReviewWorkbench", 1
    )[1].split("function navigationTerrainMapLibreCoordinates", 1)[0]
    weather_adapter = html.split("function applyWeatherCwaMapFrame", 1)[1].split(
        "function bindWeatherCwaMapFrame", 1
    )[0]

    for attribute in (
        "data-dashboard-map-hint-title",
        "data-dashboard-map-hint-summary",
        "data-dashboard-map-hint-source",
    ):
        assert attribute not in navigation_host
    for status in ("dem", "coverage", "scope"):
        assert f'data-navigation-terrain-header-status="{status}"' in navigation_workbench
    assert "bindWeatherCwaEvidenceHints(frame)" in weather_adapter
    assert "data-evidence-type" in html.split(
        "function bindWeatherCwaEvidenceHints", 1
    )[1].split("function applyWeatherCwaMapFrame", 1)[0]
    assert "pointerover" in html.split(
        "function bindWeatherCwaEvidenceHints", 1
    )[1].split("function applyWeatherCwaMapFrame", 1)[0]
    assert "focusin" in html.split(
        "function bindWeatherCwaEvidenceHints", 1
    )[1].split("function applyWeatherCwaMapFrame", 1)[0]

    fit_rule = html.split(".navigation-terrain-maplibre-fit {", 1)[1].split(
        "}", 1
    )[0]
    assert "top: 138px" in fit_rule


def test_dashboard_q0058_not_checked_is_warning_but_failed_probe_stays_red() -> None:
    html = PAGE.read_text(encoding="utf-8")
    diagnostic = html.split("async function diagnosticCheck009()", 1)[1].split(
        "async function diagnosticCheck010()", 1
    )[0]

    assert 'readiness.level === "not_checked"' in diagnostic
    assert "return diagnosticWarning(" in diagnostic
    assert 'readiness.level === "ready"' in diagnostic
    assert "Assistant is not ready" in diagnostic


def test_dashboard_q0060_shared_readability_and_q0061_living_containment() -> None:
    html = PAGE.read_text(encoding="utf-8")
    readable_rule = html.split(
        "/* qualification-shared-compact-readability */", 1
    )[1].split("}", 1)[0]

    assert "--dashboard-compact-readable-size: 11px" in html
    for selector in (
        ".field-instrument-theme .truth-item > span",
        ".dashboard-map-controls output",
        ".permission-eyebrow",
        ".permission-node small",
        ".permission-node code",
        ".permission-policy",
        ".permission-summary-tile span",
        ".permission-summary-tile small",
        ".permission-day-map figcaption",
        ".permission-day-map-source",
        ".permission-day-label",
        ".permission-day-location small",
        ".permission-day-route code",
        ".permission-day-meta",
        ".permission-day-evidence",
        ".permission-simulation-form label",
        ".weather-layer-control small",
        ".navigation-terrain-boundary-chips span",
        ".runtime-log-index-button small",
        ".runtime-audit-health-card small",
    ):
        assert selector in readable_rule
    assert "font-size: var(--dashboard-compact-readable-size)" in readable_rule
    assert "font-weight: 700" in readable_rule

    living_rule = html.split(
        "/* qualification-living-mobile-long-token-containment */", 1
    )[1].split("}", 1)[0]
    assert "min-width: 0" in living_rule
    assert "max-width: 100%" in living_rule
    assert "overflow-wrap: anywhere" in living_rule
    assert "word-break: break-word" in living_rule
    assert "const LIVING_REFRESH_INTERVAL_MS = 3000" in html


def test_dashboard_route_architecture_intelligence_workbench_contract() -> None:
    html = PAGE.read_text(encoding="utf-8")

    for marker in (
        'data-route-architecture-intelligence="true"',
        "Route Fingerprint",
        "Golden-route start-to-finish axis",
        "crowd gaps lower confidence but never rebase or truncate the route",
        "full golden-route scope retained",
        "Crowd sources / usable",
        "Reference / scope",
        "Segment Microscope",
        "Retreat dependency",
        "Evidence ledger",
        "function architectureSnapshot()",
        "function renderRouteFingerprint",
        "function architectureElevationProfile",
        "function architectureElevationPaths",
        "Golden GPX Elevation × Architecture Metrics",
        "GOLDEN ELEVATION",
        "COMPOSITE",
        "ENDURANCE",
        "PACE VAR",
        'data-architecture-elevation-profile="true"',
        'data-architecture-axis-basis="golden-gpx-distance"',
        "source_to_golden_scale",
        'data-route-fingerprint="partial"',
        "function architecturePassageTimingNodes",
        "function architecturePassageNodeById",
        "function architectureBinForDistance",
        "function architectureStructureNodes",
        "function architectureStructureNodeMarker",
        "function architecturePassageDurationLabel",
        "MCP / DIFFICULTY CP",
        "SELECTED CP / MCP PASSAGE",
        "CP = HIGH PRESSURE · MCP = ROUTE DETAIL",
        "MIN / AVG / MODE / MAX",
        'data-architecture-passage-node-id="${escapeHtml(node.node_id)}"',
        'data-architecture-difficulty-cp-count="${difficultyCpCount}"',
        'data-architecture-context-mcp-count="${contextMcpCount}"',
        "Amber diamond · difficulty CP",
        "Cyan point · MCP",
        "state.architectureSelectedPassageNodeId",
        'data-architecture-selection-surface="map-evidence"',
        'data-architecture-selection-surface="fingerprint-structure"',
        'data-architecture-passage-selected="${isSelected ? "true" : "false"}"',
        "mode_5min",
        "named_places",
        "const sourceRouteDistance = Number(",
        "function renderArchitectureMap",
        'data-architecture-mobility-status="${bins.length ? "ready" : "pending"}"',
        'data-layer-group="route-structure"',
        "function architectureLensLegendItems",
        "function architectureLensLegendSubtitle",
        "function renderArchitectureLensLegend",
        "function renderSegmentMicroscope",
        "function bindArchitectureControls",
        'data-architecture-mode="${id}"',
        'data-architecture-lens="${id}"',
        'data-architecture-mobile-view="${id}"',
        '["structure", "Structure"]',
        '["demand", "Demand"]',
        '["reversibility", "Reversibility"]',
        '["evidence", "Evidence"]',
        '["terrain_demand", "Terrain"]',
        '["slow_passage", "Slow passage"]',
        '["risk_passage", "Risk passage"]',
        '["evidence_quality", "Evidence"]',
        '["spine", "Spine"]',
        '["map", "Map"]',
        '["segment", "Segment"]',
        'data-layer-group="segments"',
        'aria-label="Architecture lens color legend"',
        'data-architecture-legend="${escapeHtml(state.architectureLens)}"',
        "Very high · 78–100",
        "No observed bin",
        "Unverified segment reversibility",
        "green means stronger evidence support; this is confidence, not pressure",
        "gray means unverified candidate topology; it is not a safe-return claim",
        "candidate-only · runtime safety truth=false",
        "normalized route architecture missing",
        "compiled mission graph missing",
        "const flattenedCoordinates = coordinates.length ? coordinates : coordinateSegments.flat();",
        "route.bbox_wgs84 || route.bounds || route.display_bounds || display.bounds",
        "coordinateSegments.length && flattenedCoordinates.length >= 2",
        "rawBounds.north",
        "rawBounds.south",
        "rawBounds.east",
        "rawBounds.west",
    ):
        assert marker in html

    for removed_marker in (
        'class="architecture-hero"',
        'class="architecture-summary-board"',
        ".architecture-hero {",
        ".architecture-summary-board {",
        "Read the route as a system.",
    ):
        assert removed_marker not in html

    assert 'if (route === "outdoor-architecture") return true;' in html.split(
        "function routeUsesWideFrame", 1
    )[1].split("function routeUsesFullFrame", 1)[0]
    assert '"outdoor-architecture": Object.freeze({maturity: "partial"' in html
    legend_rule = html.split(".architecture-map-legend {", 1)[1].split("}", 1)[0]
    assert "position: static;" in legend_rule
    assert "position: absolute;" not in legend_rule
    assert "border-top: 1px solid var(--line);" in legend_rule
    assert "fetch(" not in html.split("function architectureSnapshot", 1)[1].split(
        "function renderPaceFitPage", 1
    )[0]
    map_renderer = html.split("function renderArchitectureMap", 1)[1].split(
        "function architectureReasonLabel", 1
    )[0]
    assert "const mapContent = mapData.connected ?" in map_renderer
    assert "mapData.connected && bins.length ?" not in map_renderer
    architecture_binding = html.split("function bindArchitectureControls", 1)[
        1
    ].split("function embeddedPretripLayerInput", 1)[0]
    assert 'state.architectureSelectedPassageNodeId = "";' in architecture_binding
    assert "architecturePassageNodeById(nodeId)" in architecture_binding
    assert "architectureBinForDistance(distanceM)" in architecture_binding
    assert "const nodeTarget = selectedNodeId" in architecture_binding
    assert "const binTarget = selectedBinId" in architecture_binding
    assert "const target = nodeTarget || binTarget;" in architecture_binding
    assert "const centerArchitectureMapSelection" in architecture_binding
    assert "controller.focusElements(targets" in architecture_binding
    assert 'centerMap: focusSurface.startsWith("fingerprint")' in architecture_binding
    assert "routeDistanceM: target.dataset.architectureRouteDistanceM" in architecture_binding
    assert 'data-architecture-route-distance-m="${' in html


def test_dashboard_architecture_map_focuses_distance_bound_evidence() -> None:
    html = PAGE.read_text(encoding="utf-8")

    hit_target_rule = html.split(
        '.architecture-map-canvas [data-architecture-selection-surface="map-bin"] {',
        1,
    )[1].split("}", 1)[0]
    assert "pointer-events: stroke" in hit_target_rule
    assert "scroll-margin-top: 84px" in hit_target_rule

    map_slices = html.split("function architectureMapSlices", 1)[1].split(
        "function architectureMapCheckpointPoints", 1
    )[0]
    assert "dashboardMapMeasuredCoordinateSegments" in map_slices
    assert "measured.totalDistanceM" in map_slices
    assert "dashboardMapDistanceM" in map_slices
    assert "pairIndex" not in map_slices
    assert "totalPairs" not in map_slices
    assert "const orderedGroups = [" in map_slices
    assert "...groups.filter(group => !group.selected)" in map_slices
    assert "...groups.filter(group => group.selected)" in map_slices
    assert "return orderedGroups.map(group =>" in map_slices

    map_controller = html.split("function createDashboardMapViewportController", 1)[
        1
    ].split("function bindDashboardMapViewports", 1)[0]
    assert "const minimumZoom = Math.max(" in map_controller
    assert "Math.max(viewState.zoom, minimumZoom)" in map_controller

    architecture_binding = html.split("function bindArchitectureControls", 1)[
        1
    ].split("function embeddedPretripLayerInput", 1)[0]
    assert '"Architecture selection focused on map."' in architecture_binding
    assert "{minimumZoom: 4}" in architecture_binding
    assert 'centerMap: state.architectureMobileView === "map"' in architecture_binding


def test_dashboard_architecture_distance_measurement_uses_geometry_not_point_count() -> None:
    html = PAGE.read_text(encoding="utf-8")
    distance_helper = "function dashboardMapCoordinateDistanceMeters" + html.split(
        "function dashboardMapCoordinateDistanceMeters", 1
    )[1].split("function dashboardMapMeasuredCoordinateSegments", 1)[0]
    measurement_helper = "function dashboardMapMeasuredCoordinateSegments" + html.split(
        "function dashboardMapMeasuredCoordinateSegments", 1
    )[1].split("function dashboardMapPointPosition", 1)[0]
    node_program = "\n".join(
        (
            "const asArray = value => Array.isArray(value) ? value : [];",
            distance_helper,
            measurement_helper,
            """
const denseStart = [[
  {lat: 0, lon: 0},
  {lat: 0, lon: 0.0002},
  {lat: 0, lon: 0.0004},
  {lat: 0, lon: 0.0006},
  {lat: 0, lon: 0.0008},
  {lat: 0, lon: 0.0010},
  {lat: 0, lon: 0.0100},
]];
const measured = dashboardMapMeasuredCoordinateSegments(denseStart);
const disconnected = dashboardMapMeasuredCoordinateSegments([
  [{lat: 0, lon: 0}, {lat: 0, lon: 0.001}],
  [{lat: 1, lon: 1}, {lat: 1, lon: 1.001}],
]);
process.stdout.write(JSON.stringify({
  total: measured.totalDistanceM,
  densePrefix: measured.coordinateSegments[0][5].dashboardMapDistanceM,
  last: measured.coordinateSegments[0][6].dashboardMapDistanceM,
  disconnectedTotal: disconnected.totalDistanceM,
  sourceMutated: Object.prototype.hasOwnProperty.call(
    denseStart[0][5],
    "dashboardMapDistanceM",
  ),
}));
""",
        )
    )

    result = subprocess.run(
        ["node"],
        input=node_program,
        text=True,
        capture_output=True,
        check=True,
    )
    payload = json.loads(result.stdout)

    assert 1100 < payload["total"] < 1125
    assert 105 < payload["densePrefix"] < 117
    assert payload["last"] == payload["total"]
    assert 210 < payload["disconnectedTotal"] < 225
    assert payload["sourceMutated"] is False


def test_dashboard_qgis_feature_samples_remain_candidate_only_and_toggleable() -> None:
    html = PAGE.read_text(encoding="utf-8")

    assert "qgis_terrain_feature_sample" in html
    assert 'key: "features", kind: "qgis_terrain_feature_sample"' in html
    assert 'data-qgis-layer-toggle="${escapeHtml(definition.key)}"' in html
    assert (
        'if (!["slope", "features", "ridges", "valleys", "streams"].includes(key)) return;'
        in html
    )
    assert 'key: "ridges", kind: "qgis_candidate_ridge_line"' in html
    assert 'key: "valleys", kind: "qgis_candidate_valley_line"' in html
    assert 'key: "streams", kind: "qgis_candidate_stream_network"' in html
    assert "definition.count > 0" in html
    assert "scout-qgis-terrain-feature-samples" in html
    assert "features.push(...qgisSpatialMaplibreFeatures());" in html
    qgis_projection = html.split("function qgisSpatialWorkflowFeatures", 1)[1].split(
        "function qgisSpatialMaplibreFeatures", 1
    )[0]
    assert 'kind !== "qgis_candidate_route"' in qgis_projection
    assert 'kind !== "qgis_analysis_input_route"' in qgis_projection
    assert "candidate_only: true" in qgis_projection
    assert "runtime_safety_truth: false" in qgis_projection
    assert "operational: false" in qgis_projection
    assert '"QGIS render artifact"' in html
    assert "live QGIS render artifact" not in html
    assert "QGIS outputs remain derived reference layers" in html


def test_dashboard_qgis_disabled_state_skips_empty_latest_run_discovery() -> None:
    html = PAGE.read_text(encoding="utf-8")
    loader = html.split("async function loadQgisSpatialData", 1)[1].split(
        "async function loadQgisSpatialWorkflow", 1
    )[0]

    assert (
        'const shouldDiscoverLatestWorkflow = state.qgisSpatialStatus?.availability !== "disabled";'
        in loader
    )
    assert "if (shouldDiscoverLatestWorkflow)" in loader
    assert "state.qgisSpatialWorkflow?.workflow_run_id" in loader
    assert "rememberedQgisSpatialWorkflowRunId()" in loader
    assert "`${basePath}/workflows/latest`" in loader


def test_dashboard_terrain_candidates_use_golden_route_start_corridor() -> None:
    html = PAGE.read_text(encoding="utf-8")

    assert "const QGIS_GOLDEN_ROUTE_START_DISTANCE_M = 10;" in html
    assert "qgisSpatialAnalysisRoute" in html
    assert "async function loadQgisSpatialAnalysisRoute" in html
    assert "function navigationTerrainCandidateStartsWithinGoldenRouteCorridor" in html
    assert "hidden_by_start_corridor" in html

    distance_helper = (
        "function navigationTerrainPointToSegmentDistanceM"
        + html.split("function navigationTerrainPointToSegmentDistanceM", 1)[1].split(
            "function navigationTerrainFeatureStartCoordinate", 1
        )[0]
    )
    start_helper = (
        "function navigationTerrainFeatureStartCoordinate"
        + html.split("function navigationTerrainFeatureStartCoordinate", 1)[1].split(
            "function navigationTerrainGoldenRouteCorridorIndex", 1
        )[0]
    )
    index_helper = (
        "function navigationTerrainGoldenRouteCorridorIndex"
        + html.split("function navigationTerrainGoldenRouteCorridorIndex", 1)[1].split(
            "function navigationTerrainCandidateStartsWithinGoldenRouteCorridor", 1
        )[0]
    )
    corridor_helper = (
        "function navigationTerrainCandidateStartsWithinGoldenRouteCorridor"
        + html.split(
            "function navigationTerrainCandidateStartsWithinGoldenRouteCorridor", 1
        )[1].split("function qgisSpatialWorkflowFeatures", 1)[0]
    )
    node_program = "\n".join(
        (
            "const QGIS_GOLDEN_ROUTE_START_DISTANCE_M = 10;",
            distance_helper,
            start_helper,
            index_helper,
            corridor_helper,
            """
const route = [[121, 24], [121.01, 24]];
const corridorIndex = navigationTerrainGoldenRouteCorridorIndex(route);
const near = {geometry: {type: "LineString", coordinates: [[121.001, 24.000045], [121.002, 24.000045]]}};
const far = {geometry: {type: "LineString", coordinates: [[121.001, 24.000180], [121.002, 24.000180]]}};
const nearPolygon = {geometry: {type: "Polygon", coordinates: [[[121.001, 24.000045], [121.002, 24.000045], [121.001, 24.000045]]]}};
const farPolygon = {geometry: {type: "Polygon", coordinates: [[[121.001, 24.000180], [121.002, 24.000180], [121.001, 24.000180]]]}};
process.stdout.write(JSON.stringify({
  near: navigationTerrainCandidateStartsWithinGoldenRouteCorridor(near, route),
  far: navigationTerrainCandidateStartsWithinGoldenRouteCorridor(far, route),
  nearPolygon: navigationTerrainCandidateStartsWithinGoldenRouteCorridor(nearPolygon, route),
  farPolygon: navigationTerrainCandidateStartsWithinGoldenRouteCorridor(farPolygon, route),
  nearIndexed: navigationTerrainCandidateStartsWithinGoldenRouteCorridor(near, route, 10, corridorIndex),
  farIndexed: navigationTerrainCandidateStartsWithinGoldenRouteCorridor(far, route, 10, corridorIndex),
}));
""",
        )
    )
    result = subprocess.run(
        ["node"],
        input=node_program,
        text=True,
        capture_output=True,
        check=True,
    )
    assert json.loads(result.stdout) == {
        "near": True,
        "far": False,
        "nearPolygon": True,
        "farPolygon": False,
        "nearIndexed": True,
        "farIndexed": False,
    }


def test_scout_terrain_lines_use_route_corridor_touch_not_extraction_start() -> None:
    html = PAGE.read_text(encoding="utf-8")
    feature_collection = html.split(
        "function navigationTerrainMapLibreFeatureCollection", 1
    )[1].split("function navigationTerrainMapLibreEventFeatureCollection", 1)[0]
    qgis_projection = html.split("function qgisSpatialWorkflowFeatures", 1)[1].split(
        "function qgisSpatialMaplibreFeatures", 1
    )[0]

    assert "function navigationTerrainCandidateTouchesGoldenRouteCorridor" in html
    assert "navigationTerrainCandidateTouchesGoldenRouteCorridor(" in feature_collection
    assert "navigationTerrainCandidateStartsWithinGoldenRouteCorridor(" in qgis_projection
    assert "function navigationTerrainMapLibreVisibilitySummary" in html
    assert "displayed_line_count" in html
    assert "raw_line_count" in html
    assert 'navigationTerrainCandidateScope: "route"' in html
    assert 'data-navigation-terrain-candidate-scope="${mode}"' in html
    assert 'navigationTerrainCandidateScope() === "all"' in feature_collection
    assert 'querySelectorAll("button[data-navigation-terrain-candidate-scope]")' in html

    helpers = (
        "function navigationTerrainPointToSegmentDistanceM"
        + html.split("function navigationTerrainPointToSegmentDistanceM", 1)[1].split(
            "function qgisSpatialWorkflowFeatures", 1
        )[0]
    )
    node_program = "\n".join(
        (
            "const QGIS_GOLDEN_ROUTE_START_DISTANCE_M = 10;",
            helpers,
            """
const route = [[121, 24], [121.01, 24]];
const corridorIndex = navigationTerrainGoldenRouteCorridorIndex(route);
const touchesLater = {geometry: {type: "LineString", coordinates: [[121.001, 24.000180], [121.002, 24.000045]]}};
const alwaysFar = {geometry: {type: "LineString", coordinates: [[121.001, 24.000180], [121.002, 24.000180]]}};
process.stdout.write(JSON.stringify({
  startOnly: navigationTerrainCandidateStartsWithinGoldenRouteCorridor(touchesLater, route, 10, corridorIndex),
  touchesLater: navigationTerrainCandidateTouchesGoldenRouteCorridor(touchesLater, route, 10, corridorIndex),
  alwaysFar: navigationTerrainCandidateTouchesGoldenRouteCorridor(alwaysFar, route, 10, corridorIndex),
}));
""",
        )
    )
    result = subprocess.run(
        ["node"],
        input=node_program,
        text=True,
        capture_output=True,
        check=True,
    )
    assert json.loads(result.stdout) == {
        "startOnly": False,
        "touchesLater": True,
        "alwaysFar": False,
    }


def test_navigation_maplibre_lenses_drive_distinct_bounded_overlay_features() -> None:
    html = PAGE.read_text(encoding="utf-8")
    lens_features = html.split(
        "function navigationTerrainMapLibreLensOverlayFeatures", 1
    )[1].split("function navigationTerrainMapLibreFeatureCollection", 1)[0]
    style = html.split("function navigationTerrainMapLibreStyle", 1)[1].split(
        "function destroyNavigationTerrainMapLibre", 1
    )[0]
    initializer = html.split(
        "async function initializeNavigationTerrainMapLibre()", 1
    )[1].split("function navigationTerrainSelectedHierarchyEdge", 1)[0]

    for lens in ("structure", "pressure", "risk", "retreat", "events"):
        assert f'case "{lens}"' in lens_features
    for feature_kind in (
        "terrain_structure_sample",
        "route_pressure_sample",
        "terrain_risk_candidate",
        "retreat_route",
        "retreat_origin",
        "retreat_destination",
    ):
        assert feature_kind in lens_features
    for layer_id in (
        "scout-terrain-structure-samples",
        "scout-route-pressure-samples",
        "scout-terrain-risk-candidates",
        "scout-retreat-route",
        "scout-retreat-endpoints",
    ):
        assert f'id: "{layer_id}"' in style

    assert "function navigationTerrainMapLibreLensSummary" in html
    assert "lensSummary.status_text" in initializer
    assert 'map.once("idle", markTwoDimensionalMapReady);' in initializer
    assert "map.areTilesLoaded()" in initializer
    assert 'feature?.properties?.feature_class === "terrain_structure_sample"' in html
    assert 'feature?.properties?.feature_class === "terrain_risk_candidate"' in html
    assert "candidate_only: true" in lens_features
    assert "runtime_safety_truth: false" in lens_features
    assert "operational: false" in lens_features


def test_navigation_candidate_selection_is_explicit_navigable_and_map_linked() -> None:
    html = PAGE.read_text(encoding="utf-8")
    initializer = html.split(
        "async function initializeNavigationTerrainMapLibre()", 1
    )[1].split("function navigationTerrainSelectedHierarchyEdge", 1)[0]
    controls = html.split("function bindNavigationTerrainControls()", 1)[1].split(
        "function renderOutdoorPage", 1
    )[0]

    for marker in (
        "function navigationTerrainSelectionModel(",
        "function setNavigationTerrainSelection(",
        "function navigationTerrainSelectionFocusTarget(",
        "function focusNavigationTerrainSelection(",
        "function renderNavigationCandidateNavigator(",
        'data-navigation-candidate-select="true"',
        'data-navigation-selection-step="-1"',
        'data-navigation-selection-step="1"',
        'data-navigation-selection-current="',
        "navigationSelectedPressurePointId",
    ):
        assert marker in html

    assert '"scout-route-pressure-samples"' in initializer
    assert 'feature?.properties?.feature_class === "route_pressure_sample"' in initializer
    assert "state.navigationSelectedPressurePointId = pressureId" in initializer
    assert "navigationTerrainClickHitBox(event.point)" in initializer
    assert "setNavigationTerrainSelection(lens, select.value)" in controls
    assert "setNavigationTerrainSelection(lens, target.id)" in controls
    assert "focusNavigationTerrainSelection(lens, select.value)" in controls
    assert "focusNavigationTerrainSelection(lens, target.id)" in controls
    assert "requestedGeneration = navigationTerrainMapLibreRuntime.generation" in html
    assert "requestedGeneration !== navigationTerrainMapLibreRuntime.generation" in html
    assert 'focusNavigationTerrainSelection("structure", structureId)' in initializer
    assert 'focusNavigationTerrainSelection("pressure", pressureId)' in initializer
    assert 'focusNavigationTerrainSelection("risk", riskId)' in initializer
    assert 'id: "scout-selected-marker-halo"' in html
    assert 'id: "scout-selected-event-halo"' in html
    assert 'host.dataset.navigationTerrainFocusedSelectionId = target.id' in html
    assert 'const minimumZoom = entry.mode === "3d" ? 16 : 15' in html
    assert "pitch: entry.map.getPitch()" in html
    assert "bearing: entry.map.getBearing()" in html
    assert "function renderNavigationReviewQueue(" not in html
    assert "data-navigation-review-decision" not in html
    assert "UNSAVED LOCAL DRAFT" not in html


def test_dashboard_qgis_render_is_collapsed_audit_receipt_not_map_comparison() -> None:
    html = PAGE.read_text(encoding="utf-8")

    assert "QGIS 執行快照" in html
    assert "AUDIT RECEIPT · NOT MAP COMPARISON" in html
    assert "地形比對請使用上方 MapLibre 互動疊圖" in html
    assert '<details class="qgis-render-evidence">' in html
    assert '<details class="qgis-render-evidence" open>' not in html
