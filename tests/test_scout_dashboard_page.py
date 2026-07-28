from __future__ import annotations

import json
import subprocess
import time
import zipfile
from pathlib import Path

from fastapi.testclient import TestClient

import admin_api
from admin_api import create_admin_app


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
    assert "chilai_nanhua_day1_scoutAI route map" in html


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
    assert 'return route === "agent" || route === "debug" || route === "diagnostic" || route === "emergency" || route === "outdoor-route-context" || route === "outdoor-pace-fit" || route === "outdoor-pace-fit-body-index";' in html
    assert "routeUsesFullFrame(route)" in html
    assert 'return route === "map";' in html
    assert "/debug-projection`" not in html


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

    for action in ("clone", "transfer", "pack", "restore", "delete"):
        assert f'data-workspace-action="{action}"' in html

    assert 'data-workspace-structure="true"' in html
    assert 'data-workspace-cache="true"' in html
    assert 'data-workspace-operations="true"' in html
    assert 'id="workspaceOperationStatus"' in html
    assert 'id="workspaceRedirectProjectInput"' in html
    assert 'id="workspaceSwitchProject"' in html
    assert 'id="workspaceRefreshExternalEvidence"' in html
    assert "operator intent only" in html
    assert "Only an append-only request record is written by this dashboard." in html
    assert "Delete requires an explicit destructive approval outside this dashboard." in html
    assert 'fetchJson("/admin/dashboard/workspaces")' in html
    assert "/operation-requests" in html
    assert 'operation: operationName' in html
    assert "confirm_record: true" in html
    assert "triggerDashboardConnectedPreparation(\"workspace-operator-refresh\"" in html
    assert "External refresh may use network services and update candidate evidence." in html
    assert 'localStorage.setItem("scout.dashboardProjectId", nextProjectId)' in html
    assert 'url.searchParams.set("projectId", nextProjectId)' in html
    assert 'url.hash = "features-workspace";' in html
    assert "validateWorkspaceSelection(nextProjectId)" in html
    assert "const WORKSPACE_ROOT =" not in html
    assert "void loadConnectedPreparationStatus();" in html
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
        "Info Sections",
        "Review Groups",
        "Review Queue",
    ):
        assert group_name in html

    assert 'data-evidence-tab="${escapeHtml(tab.id)}"' in html
    assert 'rerenderEvidenceContext("timeline", selectedTab);' in html
    assert 'rerenderEvidenceContext("map", selectedTab);' in html


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
    assert 'id="dashboardMapPreview"' in html
    assert 'id="dashboardMapPreviewStatus"' in html
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
    assert "pretripMapHasRenderedTargets" in html
    assert "Loading pre-trip timeline evidence for map focus." in html
    assert "function pretripEvidenceGroupOpen(_group, _index)" in html
    assert "mapWindow.focusMapFor" in html
    assert "mapWindow.selectEvidence" in html
    assert "data-map-evidence-source" in html
    assert "data-map-target-ids" in html
    assert 'const mapToolRight = state.mapEvidenceCollapsed ? "14px" : "418px";' in html
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
    assert "SCOUT_LAYER_IDS.map((layerId, index)" in html
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
        "dashboard-map-preview",
        "pace-fit-map",
        "architecture-map",
        "navigation-training-map",
        "navigation-workspace-map",
    ):
        assert f'renderDashboardMapViewport("{viewport_id}"' in html

    assert "mapViewportById: {}" in html
    assert 'role="region"' in html
    assert 'tabindex="0"' in html
    assert "ArrowUp ArrowDown ArrowLeft ArrowRight + - 0 P B Escape" in html
    assert "ArrowUp ArrowDown ArrowLeft ArrowRight + - 0 P Escape" in html
    assert 'data-map-mouse-zoom="${mouseZoomEnabled ? "true" : "false"}"' in html
    assert 'data-map-wheel-zoom="${wheelZoomEnabled ? "true" : "false"}"' in html
    assert "data-dashboard-map-stage" in html
    assert "data-dashboard-map-selection" in html
    assert "drag down-right to zoom in; drag up-left to zoom out" in html


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


def test_weather_embedded_map_uses_only_rudy_tw_tiles_and_cwa_rainfall() -> None:
    html = PAGE.read_text(encoding="utf-8")
    pretrip_html = PRETRIP_PAGE.read_text(encoding="utf-8")
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
    assert '"cwa-qpf"' in weather_layer_contract
    assert weather_layer_contract.count('"') == 4
    assert "&mapOnly=1&wheelZoom=0&initialLayers=${encodeURIComponent(" in weather_section
    assert "WEATHER_EMBEDDED_MAP_LAYER_IDS.join" in weather_section
    assert "SCOUT_LAYER_IDS.forEach(layerId =>" in weather_frame_adapter
    assert (
        "WEATHER_EMBEDDED_MAP_LAYER_IDS.includes(layerId)"
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
    assert 'wmtsLayer: "rudy_twmap"' in pretrip_html
    assert 'sourceKind: "wmts_kvp_tile"' in pretrip_html
    assert "renderRasterBasemapLayers(state.view);" in map_viewport_adapter


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


def test_weather_hydrology_controls_are_owned_by_six_axis_weather_not_map() -> None:
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
        'WEATHER_LAYER_IDS.map(layerId => [layerId, layerId === "cwa-qpf"])'
        in html
    )
    assert "...WEATHER_LAYER_DEFAULTS" in html
    assert 'aria-label="Weather and hydrology layer controls"' in weather_renderer
    assert 'data-weather-layer-control="${escapeHtml(layer.id)}"' in weather_renderer
    assert "renderDashboardCwaImageryControls()" not in map_evidence_renderer
    assert "excludeWeatherLayersFromMapFrame(frame)" in map_frame_adapter
    assert "function setEmbeddedPretripLayerEnabled" in html
    assert "function syncWeatherLayerControls" in html
    assert "function excludeWeatherLayersFromMapFrame" in html

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


def test_scout_dashboard_navigation_terrain_intelligence_workbench_contract() -> None:
    html = PAGE.read_text(encoding="utf-8")
    navigation = html.split("function renderNavigationPage", 1)[1].split(
        "function architectureSnapshot", 1
    )[0]

    for marker in (
        'data-navigation-terrain-intelligence="true"',
        'data-terrain-contour-map="true"',
        'data-terrain-feature-detail="true"',
        'data-terrain-reading-checklist="true"',
        'data-navigation-boundary="candidate-only"',
        "function navigationTerrainFeatures()",
        "function renderNavigationTerrainMap(",
        "function renderNavigationTerrainDetail(",
        "function bindNavigationTerrainControls()",
        "bindNavigationTerrainControls();",
        "navigationSelectedFeatureId",
        "navigationSelectedLivePointId",
        "navigationSelectedStructurePointId",
        "navigationSelectedTerrainEventId",
        "navigationTerrainLens",
        "navigationTerrainSourceMode",
        "navigationTerrainData",
        "loadNavigationTerrainData",
        "function renderNavigationWorkspaceMap(",
        "function renderNavigationFeatureExtraction(",
        "function renderNavigationSourceLedger(",
        "function renderNavigationOrderedClues(",
        "function renderNavigationTopology(",
        "function renderNavigationEvidenceGaps(",
        "function renderNavigationEvidenceWorkbench(",
        "function navigationTerrainHierarchyPath(",
        "function renderNavigationTerrainEventTimeline(",
        "function renderNavigationTerrainEventDetail(",
        'data-navigation-workspace-map="true"',
        'data-navigation-structure-point-id="',
        'data-navigation-structure-kind="',
        'data-navigation-route-path="true"',
        'data-navigation-terrain-edge-kind="',
        'data-navigation-terrain-event-id="',
        'data-navigation-terrain-event-timeline="true"',
        'data-navigation-source-ledger="true"',
        'data-navigation-ordered-clues="true"',
        'data-navigation-route-topology="true"',
        'data-navigation-historical-option="',
        'data-navigation-evidence-gaps="true"',
        "Workspace DEM + candidate morphology",
        "Prepared DTM + GPX source ledger",
        "主稜／支稜",
        "看到什麼",
        "走錯徵兆",
        "回復檢查",
        "/navigation-terrain-intelligence",
    ):
        assert marker in html

    for lens, label in (
        ("structure", "地形結構"),
        ("pressure", "坡度壓力"),
        ("risk", "風險地形"),
        ("retreat", "撤退方向"),
        ("events", "路線事件"),
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
    assert "需要來源與人工複核" in navigation
    assert 'role="listitem"\n                class="navigation-event-card"' not in navigation
    assert "void loadConnectedPreparationStatus();" in html
    assert 'const pageHeaderHidden = route === "outdoor-navigation";' in html
    assert (
        'dashboardShell?.classList.toggle("is-page-header-hidden", pageHeaderHidden);'
        in html
    )
    assert ".dashboard-shell.is-page-header-hidden .topbar {" in html
    assert ".dashboard-shell.is-page-header-hidden .dashboard-frame {" in html
    assert 'class="navigation-terrain-brief"' not in navigation
    assert "data-navigation-terrain-source=" not in navigation
    assert 'class="navigation-reading-header"' in html
    assert '<summary class="navigation-reading-summary">' in html
    assert navigation.count("${renderNavigationReadingChecklist()}") == 1
    assert navigation.index("${renderNavigationReadingChecklist()}") < navigation.index(
        'class="navigation-terrain-lenses"'
    )
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

    for marker in (
        "const NAVIGATION_RUDY_TILE_SOURCE",
        'sourceKind: "wmts_kvp_tile"',
        'wmtsLayer: "rudy_twmap"',
        "function navigationMercatorY(",
        "function navigationRudyTileRange(",
        "function navigationRudyBaseZoom(",
        "function navigationRudyTileUrl(",
        "function navigationRudyTileImages(",
        "function navigationRudyVisibleBounds(",
        "function updateNavigationRudyTileLayer(",
        "Math.log2(viewState.zoom)",
        'data-navigation-rudy-tile-layer="true"',
        'data-navigation-rudy-tile-zoom="',
        'data-navigation-basemap-layer="rudy-twmap"',
        "updateNavigationRudyTileLayer(viewport, viewState)",
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
    assert "drag down-right to zoom in; drag up-left to zoom out" in html
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


def test_map_navigation_weather_enforce_tile_vector_or_approved_single_image_policy() -> None:
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
    navigation_tile_refresh = html.split(
        "function updateNavigationRudyTileLayer(", 1
    )[1].split("function navigationTerrainPointPosition(", 1)[0]
    navigation_training_map = html.split(
        "function renderNavigationTerrainMap", 1
    )[1].split("function renderNavigationTerrainDetail", 1)[0]
    navigation_workspace_map = html.split(
        "function renderNavigationWorkspaceMap", 1
    )[1].split("function renderNavigationFeatureExtraction", 1)[0]

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
    assert "enforceDashboardMapRenderPolicy(viewport);" in navigation_tile_refresh


def test_map_navigation_weather_share_hover_hints_and_keyboard_pan_contract() -> None:
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

    assert 'data-route="emergency"' in html
    assert 'data-safety-emergency-console="desktop"' in emergency_page
    assert 'data-emergency-approval-frame="desktop"' in emergency_page
    assert 'src="/admin/dashboard/emergency-approval-desktop-v0"' in emergency_page
    assert 'href="/admin/dashboard/emergency-approval-desktop-v0"' in emergency_page
    assert 'title="Safety and emergency desktop approval console"' in emergency_page
    assert "Open full desktop console" in emergency_page
    assert "emergency-mobile-approval-v0" not in emergency_page
    assert 'renderMapPanel("emergency")' not in emergency_page
    assert ".safety-emergency-shell" in html
    assert ".safety-emergency-frame" in html
    assert '<header class="safety-emergency-commandbar">' not in emergency_page
    assert 'class="safety-emergency-status-grid"' not in emergency_page
    assert "safety-emergency-status-card" not in emergency_page
    assert "safety-emergency-eyebrow" not in emergency_page
    assert ".safety-emergency-commandbar" not in html
    assert ".safety-emergency-status-grid" not in html
    assert ".safety-emergency-status-card" not in html


def test_scout_dashboard_route_context_embeds_skill_trip_briefing() -> None:
    html = PAGE.read_text(encoding="utf-8")

    assert "function routeContextBriefingProjectId()" in html
    assert "function routeContextBriefingSrc()" in html
    assert "function renderRouteBriefingMetaBlock" in html
    assert "return candidate || PRETRIP_DATA_PROJECT_ID;" in html
    assert 'return route === "agent" || route === "debug" || route === "diagnostic" || route === "emergency" || route === "outdoor-route-context" || route === "outdoor-pace-fit" || route === "outdoor-pace-fit-body-index";' in html
    assert 'decisionBand(force.decision, "Scout AI route-context trip briefing loaded"' not in html
    assert "/admin/pretrip/projects/${project}/briefings/route-context" in html
    assert "data-route-context-briefing=\"true\"" in html
    assert 'class="route-briefing-meta-drawer" data-route-briefing-metadata="collapsed"' in html
    assert '<details class="route-briefing-meta-drawer" data-route-briefing-metadata="collapsed" open>' not in html
    assert "Briefing metadata" in html
    assert "route-briefing-meta-grid" in html
    assert "route-briefing-meta-block" in html
    assert "Scout AI Trip Briefing" not in html
    assert "route-briefing-ops" in html
    assert "data-route-context-briefing-regenerate" in html
    assert "Regenerate with Scout AI" in html
    assert "/briefings/route-context/regenerate" in html
    assert "function routeContextBriefingVariantsPath()" in html
    assert "function routeContextBriefingVariantsGeneratePath()" in html
    assert "function routeContextBriefingVariantFileSrc(ref)" in html
    assert "/briefings/route-context/variants" in html
    assert "/briefings/route-context/variants/generate" in html
    assert "data-route-context-briefing-variants-generate" in html
    assert "Generate 5 variants with Scout AI" in html
    assert "Calling Scout AI route-context-intelligence skill for five variants" in html
    assert "model: \"nvidia:z-ai/glm-5.2\"" in html
    assert "model_max_tokens: 7000" in html
    assert "reference_variants_dir_ref" in html
    assert "max_reference_similarity: 0.6" in html
    assert "reference similarity" in html
    assert "reference_similarity_gate" in html
    assert "Open variants index" in html
    assert "Model audit" in html
    assert "single Scout AI model call" in html
    assert "canonical briefing unchanged" in html
    assert "Calling Scout AI, then rebuilding briefing artifact" in html
    assert "Calling Scout AI via OpenRouter" not in html
    assert "Open briefing" in html
    assert "outputs/briefings/route_context_briefing.html" in html
    assert "scout-route-context-briefing skill" in html
    assert "pretrip_route_context_collection" in html
    assert "candidate-only" in html
    assert "runtime_safety_truth=false" in html
    assert "stop permission, route open/closed decision" in html
    assert "no Phase 1 mutation, no safety endpoint write" in html
    assert '["Outbound", "closed"]' in html
    assert "no live safety automation" not in html
    assert '<div class="debug-main-stack">\n            ${renderMetricPanel("Briefing Source"' not in html


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
    assert "input type=\"checkbox\" data-layer" in html
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
        'loadDataForRoute("outdoor-weather", {force: true})',
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
        "Record clone request",
        "Record transfer request",
        "Record package request",
        "Record restore request",
        "Request deletion review",
        "Preview Import",
        "Create Workspace",
        "Only an append-only request record is written by this dashboard.",
        "32 canonical layers",
        "completed-track is after-action only",
        "Permission Class Selector Preview",
        "No runtime decision",
        "Product Preview",
        "Technical Prototype",
        "Reference",
        "Static rule set",
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
    assert "Skip embedded surface" in html
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


def test_dashboard_diagnostic_page_runs_30_read_only_checks() -> None:
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
    assert 'diagnostic: ["Diagnostic", "30 read-only Dashboard checks"]' in html
    assert 'if (route === "diagnostic") return renderDiagnosticPage();' in html

    case_source = html.split(
        "const DASHBOARD_DIAGNOSTIC_CASES = Object.freeze([", 1
    )[1].split("]);", 1)[0]
    for index in range(1, 31):
        assert f'id: "DASH-{index:03d}"' in case_source
    assert case_source.count('id: "DASH-') == 30
    assert "postJson(" not in case_source

    for marker in (
        "async function diagnosticCheck026()",
        "async function diagnosticCheck027()",
        "async function diagnosticCheck028()",
        "async function diagnosticCheck029()",
        "async function diagnosticCheck030()",
        "Map、Navigation、Weather evidence hover hint",
        "三圖框選縮放與鍵盤平移",
        "三圖圖磚、向量與單圖例外政策",
        "三圖基本 Zoom、Pan 與 Fit",
        "Evidence 是否有計數為 0 的類別",
        "DASHBOARD_MAP_APPROVED_SINGLE_IMAGE_THEMES",
        "diagnosticMapSurfaceSources",
        "function diagnosticZeroCountEvidenceCategories(",
        ".filter(group => Number(group.count) === 0)",
        ".filter(item => Number(item.count) === 0)",
        "Evidence categories count=0:",
    ):
        assert marker in html

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
        'data-diagnostic-status="failed"',
        "測試中",
        "測試通過",
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
    assert 'status: "passed"' in runner
    assert 'status: "failed"' in runner
    assert "performance.now()" in runner


def test_dashboard_route_context_variants_index_uses_canonical_file_query_links() -> None:
    source = (ROOT / "tools" / "scout_ai_route_context_briefing_variants.py").read_text(
        encoding="utf-8"
    )

    assert "def _variant_file_href" in source
    assert 'f"?ref={quote(ref, safe=\'\')}"' in source
    assert '_variant_file_href(item["relative_ref"])' in source
    assert '_variant_file_href("route_context_variant_comparison.md")' in source
    assert '_variant_file_href("route_context_variant_comparison.json")' in source


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
        "function architecturePassageTimingNodes",
        "function architecturePassageDurationLabel",
        "CP/MCP PASSAGE · 500M WINDOW",
        "MIN / AVG / MODE / MAX",
        'data-architecture-passage-node-id="${escapeHtml(node.node_id)}"',
        "state.architectureSelectedPassageNodeId",
        "mode_5min",
        "named_places",
        "const sourceRouteDistance = Math.max(",
        "function renderArchitectureMap",
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
