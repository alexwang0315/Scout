import json
import shutil
from pathlib import Path

from fastapi.testclient import TestClient

from admin_api import create_admin_app
from admin_local_raster_tiles import raster_tile_cache_path


PROJECT_ID = "chilai_nanhua_day1"
ROOT = Path(__file__).resolve().parents[1]
FIXTURE_PROJECT_ROOT = ROOT / "tests" / "fixtures" / "pretrip" / "projects" / PROJECT_ID
REPO_REVIEW_DECISION_LOG = FIXTURE_PROJECT_ROOT / "reviews" / "review_decision_log.json"
REPO_REVIEW_DECISION_APPLY_PLAN = (
    FIXTURE_PROJECT_ROOT / "outputs" / "review_decision_apply_plan.json"
)
REPO_EXPERT_CONTRIBUTION_APPLY_PLAN = (
    FIXTURE_PROJECT_ROOT / "outputs" / "expert_contribution_apply_plan.json"
)
REPO_EXPERT_CONTRIBUTION_WORKSPACE_APPLY_RESULT = (
    FIXTURE_PROJECT_ROOT
    / "outputs"
    / "expert_contribution_workspace_apply_result.json"
)
REPO_ROUTE_NOTE_REVIEWED_ASSUMPTIONS = (
    FIXTURE_PROJECT_ROOT / "outputs" / "route_note_reviewed_assumptions.json"
)
ACCEPTED_CONTOUR_CANDIDATE_REF = "contour.g11.seg_001_003"
UNDECIDED_CONTOUR_CANDIDATE_REF = "contour.g11.seg_006_008"
UNDECIDED_CONTOUR_TARGET_IDS = ["seg.006", "seg.007", "seg.008"]
UNDECIDED_CONTOUR_SUMMARY = (
    "Accepted undecided contour review note as candidate-only planning context."
)
UNDECIDED_DEPARTURE_BUNDLE_CANDIDATE_REF = "departure_bundle.chilai_nanhua_day1.v0"
UNDECIDED_DEPARTURE_BUNDLE_TARGET_IDS = [
    "readiness_refs",
    "resource_plan",
    "remote_summary",
    "terrain_refs",
    "audit_refs",
]
UNDECIDED_DEPARTURE_BUNDLE_SUMMARY = (
    "Rejected frozen departure bundle candidate before local planning use."
)


def _repo_fixture_bytes() -> dict[Path, bytes]:
    return {
        path: path.read_bytes()
        for path in sorted(FIXTURE_PROJECT_ROOT.rglob("*"))
        if path.is_file()
    }


def _copy_pretrip_workspace(tmp_path: Path) -> Path:
    workspace_root = tmp_path / "pretrip_workspace"
    shutil.copytree(FIXTURE_PROJECT_ROOT, workspace_root / PROJECT_ID)
    return workspace_root


def _write_small_gpx(
    path: Path,
    *,
    name: str,
    points: list[tuple[float, float, float]],
) -> None:
    trkpts = "\n".join(
        f'      <trkpt lat="{lat}" lon="{lon}"><ele>{ele}</ele></trkpt>'
        for lat, lon, ele in points
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"""<?xml version="1.0" encoding="UTF-8"?>
<gpx version="1.1" creator="scout-test" xmlns="http://www.topografix.com/GPX/1/1">
  <trk>
    <name>{name}</name>
    <trkseg>
{trkpts}
    </trkseg>
  </trk>
</gpx>
""",
        encoding="utf-8",
    )


def _accepted_review_payload(
    *,
    candidate_ref: str = ACCEPTED_CONTOUR_CANDIDATE_REF,
    summary: str = "Accepted as candidate-only planning context.",
    persist_to_workspace: bool = False,
) -> dict[str, object]:
    return {
        "candidate_ref": candidate_ref,
        "decision": "accepted",
        "reviewer_alias": "trip_leader",
        "summary": summary,
        "persist_to_workspace": persist_to_workspace,
    }


def _rejected_review_payload(
    *,
    candidate_ref: str,
    summary: str,
    persist_to_workspace: bool = False,
) -> dict[str, object]:
    return {
        "candidate_ref": candidate_ref,
        "decision": "rejected",
        "reviewer_alias": "trip_leader",
        "summary": summary,
        "persist_to_workspace": persist_to_workspace,
    }


def _corrected_review_payload(
    *,
    candidate_ref: str,
    summary: str,
    correction_summary: str,
    persist_to_workspace: bool = False,
) -> dict[str, object]:
    return {
        "candidate_ref": candidate_ref,
        "decision": "corrected",
        "reviewer_alias": "trip_leader",
        "summary": summary,
        "correction": {
            "summary": correction_summary,
            "field_updates": {},
            "replacement_ref_ids": [],
        },
        "persist_to_workspace": persist_to_workspace,
    }


def _batch_review_payload(*decisions: dict[str, object], persist_to_workspace: bool = False) -> dict[str, object]:
    return {
        "decisions": list(decisions),
        "persist_to_workspace": persist_to_workspace,
    }


def test_pretrip_admin_page_serves_static_shell():
    client = TestClient(create_admin_app())

    response = client.get("/admin/pretrip")

    assert response.status_code == 200
    assert "Scout Phase 4 Pre-Trip Planning" in response.text
    assert "/admin/pretrip/projects/${PROJECT_ID}" in response.text
    assert "evidenceTree" in response.text
    assert "jsonPane" in response.text
    assert "segment-overlay" in response.text


def test_pretrip_projects_api_lists_fixture_projects():
    client = TestClient(create_admin_app())

    response = client.get("/admin/pretrip/projects")

    assert response.status_code == 200
    assert response.json()["projects"] == [
        {
            "project_id": PROJECT_ID,
            "name": "能高安東軍縱走 GPX corpus",
            "kind": "phase4_pretrip_fixture",
        }
    ]


def test_pretrip_project_api_returns_read_only_view_model():
    client = TestClient(create_admin_app())

    response = client.get(f"/admin/pretrip/projects/{PROJECT_ID}")

    assert response.status_code == 200
    payload = response.json()
    assert payload["project_id"] == PROJECT_ID
    assert payload["readiness"]["status"] == "ready"
    assert len(payload["checkpoints"]) == 110
    assert len(payload["segments"]) == 109
    assert payload["reference_tracks"]["reference_track_count"] == 23
    assert payload["checkpoint_events"]["event_count"] == 110
    assert payload["raw_sample_summary"]["raw_payloads_embedded"] is False
    assert payload["review_draft_log"]["status"] == "draft_only"
    assert payload["review_draft_log"]["counts"]["action_count"] == 3
    assert payload["review_draft_log"]["boundary"]["decisions_recorded"] is False
    assert payload["review_draft_log"]["boundary"]["package_mutation_allowed"] is False
    assert payload["route_note_review_options"]["counts"]["review_option_count"] == 23
    assert (
        payload["route_note_review_options"]["counts"]["decision_recorded_count"]
        == 0
    )
    assert payload["route_note_review_options"]["boundary"]["draft_only"] is True
    assert payload["route_note_review_options"]["options"][0][
        "allowed_admin_dispositions"
    ] == ["promote_hint", "promote_warning", "ignore", "field_verify"]
    assert payload["tabs"]["pre_trip_planning"]["review_draft_log"]["evidence_type"] == (
        "pretrip_review_draft_log"
    )
    assert payload["tabs"]["pre_trip_planning"]["review_draft_log"]["source_path"].endswith(
        "reviews/review_draft_log.json"
    )
    response_text = response.text
    assert "proposed_fields" not in response_text
    assert "reviewer_prompt" not in response_text
    assert "target_segment_refs" not in response_text
    assert payload["tabs"]["post_analysis"]["runtime_handoff"]["boundary"][
        "phase1_runtime_mutation_allowed"
    ] is False


def test_pretrip_project_weather_overlay_api_returns_summary_only_contract():
    client = TestClient(create_admin_app())

    response = client.get(f"/admin/pretrip/projects/{PROJECT_ID}/weather-overlay")

    assert response.status_code == 200
    payload = response.json()
    assert payload["artifact_kind"] == "admin_weather_api_overlay"
    assert payload["overlay_id"] == f"admin_weather_overlay.{PROJECT_ID}.v0"
    assert payload["layer_id"] == "weather-api"
    assert payload["status"] == "overlay_ready"
    assert payload["provider_mode"] == "fixture_backed_local_admin_api"
    assert payload["external_api_calls_made"] is False
    assert payload["authoritative_weather_computed"] is False
    assert payload["raw_payloads_embedded"] is False
    assert payload["api_runtime_status"]["ready"] is False
    assert payload["api_runtime_status"]["secret_value_embedded"] is False
    assert payload["counts"]["card_count"] == 3
    assert payload["counts"]["glyph_count"] == 2


def test_pretrip_project_weather_overlay_api_can_use_live_open_meteo_summary(
    monkeypatch,
):
    def fake_snapshot(route_bounds):
        assert route_bounds["min_lat"] < route_bounds["max_lat"]
        return {
            "artifact_kind": "open_meteo_weather_snapshot",
            "status": "live_summary_ready",
            "provider": "open_meteo",
            "source_docs_url": "https://open-meteo.com/en/docs",
            "request_url_has_secret": False,
            "coordinate": {"latitude": 24.050623, "longitude": 121.24558},
            "current": {
                "temperature_2m_c": 18.2,
                "wind_speed_10m_kmh": 12.4,
                "wind_gusts_10m_kmh": 28.0,
                "weather_code": 61,
                "cloud_cover_pct": 88,
            },
            "next_6h": {"precipitation_mm": 0.6},
            "raw_payloads_embedded": False,
            "external_api_calls_made": True,
            "authoritative_weather_computed": False,
            "human_review_required": True,
        }

    monkeypatch.setenv("SCOUT_WEATHER_API_ENABLED", "true")
    monkeypatch.setenv("SCOUT_WEATHER_API_PROVIDER", "open_meteo")
    monkeypatch.setattr("admin_api.fetch_open_meteo_weather_snapshot", fake_snapshot)
    client = TestClient(create_admin_app())

    response = client.get(f"/admin/pretrip/projects/{PROJECT_ID}/weather-overlay")

    assert response.status_code == 200
    payload = response.json()
    assert payload["provider_mode"] == "live_open_meteo_summary"
    assert payload["external_api_calls_made"] is True
    assert payload["authoritative_weather_computed"] is False
    assert payload["raw_payloads_embedded"] is False
    assert payload["api_runtime_status"]["provider"] == "open_meteo"
    assert payload["api_runtime_status"]["ready"] is True
    assert payload["live_weather_snapshot"]["request_url_has_secret"] is False
    assert "request_url" not in payload["live_weather_snapshot"]


def test_admin_osm_tile_proxy_api_returns_local_offline_fallback_tile():
    client = TestClient(create_admin_app())

    response = client.get("/admin/tiles/osm/1/1/1.png")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("image/svg+xml")
    assert response.headers["x-scout-tile-source"] == "offline_fallback"
    assert response.headers["x-scout-tile-hash"]
    assert b"OSM offline 1/1/1" in response.content


def test_admin_osm_tile_proxy_api_rejects_invalid_coords():
    client = TestClient(create_admin_app())

    response = client.get("/admin/tiles/osm/21/0/0.png")

    assert response.status_code == 422
    assert "tile z must be between" in response.json()["detail"]


def test_admin_imagery_tile_proxy_api_returns_cached_png(monkeypatch, tmp_path):
    monkeypatch.setenv("SCOUT_ADMIN_RASTER_TILE_CACHE_ROOT", str(tmp_path))
    cached_path = raster_tile_cache_path(
        "chilai_nanhua_day1",
        "imagery",
        5,
        26,
        13,
        cache_root=tmp_path,
    )
    cached_path.parent.mkdir(parents=True)
    cached_path.write_bytes(b"\x89PNG\r\n\x1a\ncached-raster-tile")
    client = TestClient(create_admin_app())

    response = client.get("/admin/tiles/imagery/chilai_nanhua_day1/imagery/5/26/13.png")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("image/png")
    assert response.headers["x-scout-tile-source"] == "local_cache"
    assert response.content == cached_path.read_bytes()


def test_admin_imagery_tile_proxy_api_returns_transparent_fallback(monkeypatch, tmp_path):
    monkeypatch.setenv("SCOUT_ADMIN_RASTER_TILE_CACHE_ROOT", str(tmp_path))
    client = TestClient(create_admin_app())

    response = client.get("/admin/tiles/imagery/chilai_nanhua_day1/imagery/5/26/13.png")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("image/svg+xml")
    assert response.headers["x-scout-tile-source"] == "transparent_fallback"
    assert b"Raster offline 5/26/13" in response.content


def test_admin_imagery_tile_proxy_api_rejects_invalid_identity():
    client = TestClient(create_admin_app())

    response = client.get("/admin/tiles/imagery/bad!/imagery/5/26/13.png")

    assert response.status_code == 422
    assert "project_id contains unsafe characters" in response.json()["detail"]


def test_unknown_pretrip_project_returns_404():
    client = TestClient(create_admin_app())

    response = client.get("/admin/pretrip/projects/missing")

    assert response.status_code == 404


def test_pretrip_project_workspace_api_creates_metadata_only_tmp_copy(tmp_path):
    original_fixture_bytes = _repo_fixture_bytes()
    workspace_root = tmp_path / "pretrip_workspace"
    workspace_project_root = workspace_root / PROJECT_ID
    client = TestClient(create_admin_app(pretrip_workspace_root=workspace_root))

    response = client.post(f"/admin/pretrip/projects/{PROJECT_ID}/workspace")

    assert response.status_code == 200
    payload = response.json()
    manifest = payload["manifest"]
    assert payload["artifact_kind"] == "pretrip_workspace_copy"
    assert payload["persisted"] is True
    assert manifest["project_id"] == PROJECT_ID
    assert manifest["workspace_root"] == str(workspace_project_root.resolve())
    assert manifest["raw_file_count"] == 0
    assert payload["boundary"]["source_mutation_allowed"] is False
    assert payload["boundary"]["package_mutation_allowed"] is False
    assert payload["boundary"]["runtime_mutation_allowed"] is False
    assert payload["boundary"]["phase1_runtime_mutation_allowed"] is False
    assert payload["boundary"]["phase2_writeback_allowed"] is False
    assert payload["boundary"]["external_api_calls_made"] is False
    assert payload["boundary"]["fixture_file_mutation_allowed"] is False
    assert payload["boundary"]["workspace_file_mutation_allowed"] is True
    assert payload["boundary"]["workspace_project_root"] == str(
        workspace_project_root.resolve()
    )
    assert payload["mutation"]["source_mutated"] is False
    assert payload["mutation"]["package_mutated"] is False
    assert payload["mutation"]["runtime_mutated"] is False
    assert payload["mutation"]["phase1_runtime_mutated"] is False
    assert payload["mutation"]["phase2_writeback_performed"] is False
    assert payload["mutation"]["fixture_files_mutated"] is False
    assert payload["mutation"]["workspace_files_mutated"] is True
    assert (workspace_project_root / "project.json").is_file()
    assert (workspace_project_root / "reviews" / "review_decision_log.json").is_file()
    assert (
        workspace_project_root / "outputs" / "review_decision_apply_plan.json"
    ).is_file()
    assert all(
        path.suffix.lower() in {".json", ".geojson", ".jsonl"}
        for path in workspace_project_root.rglob("*")
        if path.is_file()
    )
    assert _repo_fixture_bytes() == original_fixture_bytes


def test_pretrip_project_workspace_api_rejects_duplicate_create(tmp_path):
    original_fixture_bytes = _repo_fixture_bytes()
    workspace_root = tmp_path / "pretrip_workspace"
    client = TestClient(create_admin_app(pretrip_workspace_root=workspace_root))

    first_response = client.post(f"/admin/pretrip/projects/{PROJECT_ID}/workspace")
    duplicate_response = client.post(f"/admin/pretrip/projects/{PROJECT_ID}/workspace")

    assert first_response.status_code == 200
    assert duplicate_response.status_code == 409
    assert "workspace project root already exists" in duplicate_response.json()["detail"]
    assert _repo_fixture_bytes() == original_fixture_bytes


def test_pretrip_project_workspace_api_rejects_without_workspace_root():
    original_fixture_bytes = _repo_fixture_bytes()
    client = TestClient(create_admin_app())

    response = client.post(f"/admin/pretrip/projects/{PROJECT_ID}/workspace")

    assert response.status_code == 409
    assert "pretrip_workspace_root" in response.json()["detail"]
    assert _repo_fixture_bytes() == original_fixture_bytes


def test_pretrip_mcp_review_actions_write_only_workspace_log(tmp_path):
    original_fixture_bytes = _repo_fixture_bytes()
    workspace_root = _copy_pretrip_workspace(tmp_path)
    workspace_project_root = workspace_root / PROJECT_ID
    client = TestClient(create_admin_app(pretrip_workspace_root=workspace_root))

    response = client.post(
        f"/admin/pretrip/projects/{PROJECT_ID}/mcp-review-actions",
        json={
            "mcp_id": "mcp.heishuitang.002",
            "decision": "linked",
            "summary": "Link MCP to nearest Scout CP.",
            "linked_cp_candidate_id": "cp.002",
            "persist_to_workspace": True,
            "decided_at": "2026-05-27T00:00:00+00:00",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["artifact_kind"] == "pretrip_mcp_review_action"
    assert payload["counts"]["action_count"] == 1
    assert payload["boundary"]["workspace_file_mutation_allowed"] is True
    assert payload["boundary"]["runtime_mutation_allowed"] is False
    assert payload["boundary"]["phase1_runtime_mutation_allowed"] is False
    assert payload["boundary"]["compiles_mission_graph"] is False
    assert payload["mutation"]["workspace_mcp_review_log_mutated"] is True
    log_path = workspace_project_root / "outputs" / "mcp" / "mcp_review_actions.json"
    assert log_path.is_file()
    log = json.loads(log_path.read_text(encoding="utf-8"))
    assert log["actions"][0]["decision"] == "linked"
    assert log["actions"][0]["candidate_label"] == "黑水塘"
    assert log["actions"][0]["support_status"] == "supported"
    assert log["actions"][0]["runtime_safety_truth"] is False
    assert _repo_fixture_bytes() == original_fixture_bytes


def test_pretrip_mcp_review_action_preview_does_not_write_workspace(tmp_path):
    workspace_root = _copy_pretrip_workspace(tmp_path)
    workspace_project_root = workspace_root / PROJECT_ID
    client = TestClient(create_admin_app(pretrip_workspace_root=workspace_root))

    response = client.post(
        f"/admin/pretrip/projects/{PROJECT_ID}/mcp-review-actions",
        json={
            "mcp_id": "mcp.heishuitang.002",
            "decision": "accepted",
            "summary": "Preview only.",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["artifact_kind"] == "pretrip_mcp_review_action_preview"
    assert payload["preview"] is True
    assert payload["mutation"]["workspace_files_mutated"] is False
    assert not (workspace_project_root / "outputs" / "mcp" / "mcp_review_actions.json").exists()


def test_pretrip_mcp_review_actions_reject_unknown_linked_cp(tmp_path):
    workspace_root = _copy_pretrip_workspace(tmp_path)
    client = TestClient(create_admin_app(pretrip_workspace_root=workspace_root))

    response = client.post(
        f"/admin/pretrip/projects/{PROJECT_ID}/mcp-review-actions",
        json={
            "mcp_id": "mcp.heishuitang.002",
            "decision": "linked",
            "summary": "Bad CP link.",
            "linked_cp_candidate_id": "cp.missing",
            "persist_to_workspace": True,
        },
    )

    assert response.status_code == 409
    assert "unknown Scout CP candidate" in response.json()["detail"]


def test_pretrip_import_gpx_preview_validates_paths_without_writing(tmp_path):
    original_fixture_bytes = _repo_fixture_bytes()
    workspace_root = tmp_path / "pretrip_workspace"
    inbox = tmp_path / "inbox"
    reference_dir = inbox / "refs"
    golden_route = inbox / "golden-route.gpx"
    explicit_reference = inbox / "reference-explicit.gpx"
    directory_reference = reference_dir / "reference-dir.gpx"
    _write_small_gpx(
        golden_route,
        name="api preview golden route",
        points=[
            (24.0, 121.0, 1000.0),
            (24.006, 121.006, 1010.0),
            (24.012, 121.012, 1020.0),
        ],
    )
    _write_small_gpx(
        explicit_reference,
        name="api preview explicit reference",
        points=[(24.0, 121.0, 1000.0), (24.01, 121.01, 1015.0)],
    )
    _write_small_gpx(
        directory_reference,
        name="api preview directory reference",
        points=[(24.001, 121.001, 1001.0), (24.011, 121.011, 1016.0)],
    )
    client = TestClient(create_admin_app(pretrip_workspace_root=workspace_root))

    response = client.post(
        "/admin/pretrip/projects/api_preview_import/import-gpx-preview",
        json={
            "golden_route_gpx": str(golden_route),
            "reference_dir": str(reference_dir),
            "reference_gpx_paths": [str(explicit_reference)],
            "profile": "pi-offline",
            "checkpoint_spacing_m": 500.0,
            "max_reference_display_points": 3,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["artifact_kind"] == "pretrip_import_gpx_preview"
    assert payload["preview"] is True
    assert payload["persisted"] is False
    assert payload["plan"]["can_run"] is True
    assert payload["plan"]["source_file_count"] == 3
    assert payload["plan"]["golden_route_count"] == 1
    assert payload["plan"]["reference_track_count"] == 2
    assert payload["provenance"]["golden_route_gpx"]["role"] == "golden_route_reference"
    assert payload["provenance"]["golden_route_gpx"]["route_summary"]["route_name"] == (
        "api preview golden route"
    )
    assert payload["planning_semantics"]["golden_route"]["actual_user_track"] is False
    assert payload["boundary"]["runtime_mutation_allowed"] is False
    assert payload["boundary"]["phase1_runtime_mutation_allowed"] is False
    assert payload["boundary"]["phase2_writeback_allowed"] is False
    assert payload["boundary"]["final_mission_graph_compiled"] is False
    assert payload["mutation"]["workspace_files_mutated"] is False
    assert not (workspace_root / "api_preview_import").exists()
    assert "<trkpt" not in response.text.lower()
    assert _repo_fixture_bytes() == original_fixture_bytes


def test_pretrip_import_gpx_preview_rejects_missing_local_reference(tmp_path):
    workspace_root = tmp_path / "pretrip_workspace"
    golden_route = tmp_path / "golden-route.gpx"
    _write_small_gpx(
        golden_route,
        name="api missing ref golden route",
        points=[(24.0, 121.0, 1000.0), (24.01, 121.01, 1010.0)],
    )
    client = TestClient(create_admin_app(pretrip_workspace_root=workspace_root))

    response = client.post(
        "/admin/pretrip/projects/api_missing_ref/import-gpx-preview",
        json={
            "golden_route_gpx": str(golden_route),
            "reference_gpx_paths": [str(tmp_path / "missing-reference.gpx")],
        },
    )

    assert response.status_code == 404
    assert "reference GPX not found" in response.json()["detail"]
    assert not (workspace_root / "api_missing_ref").exists()


def test_pretrip_import_gpx_preview_rejects_actual_track_stage(tmp_path):
    workspace_root = tmp_path / "pretrip_workspace"
    golden_route = tmp_path / "golden-route.gpx"
    _write_small_gpx(
        golden_route,
        name="api post analysis rejected",
        points=[(24.0, 121.0, 1000.0), (24.01, 121.01, 1010.0)],
    )
    client = TestClient(create_admin_app(pretrip_workspace_root=workspace_root))

    response = client.post(
        "/admin/pretrip/projects/api_post_analysis/import-gpx-preview",
        json={
            "golden_route_gpx": str(golden_route),
            "import_stage": "post_analysis",
        },
    )

    assert response.status_code == 422
    assert not (workspace_root / "api_post_analysis").exists()


def test_pretrip_import_gpx_run_requires_confirmation(tmp_path):
    workspace_root = tmp_path / "pretrip_workspace"
    golden_route = tmp_path / "golden-route.gpx"
    _write_small_gpx(
        golden_route,
        name="api confirmation golden route",
        points=[(24.0, 121.0, 1000.0), (24.01, 121.01, 1010.0)],
    )
    client = TestClient(create_admin_app(pretrip_workspace_root=workspace_root))

    response = client.post(
        "/admin/pretrip/projects/api_requires_confirm/import-gpx",
        json={"golden_route_gpx": str(golden_route)},
    )

    assert response.status_code == 400
    assert "confirm_import=true is required" in response.json()["detail"]
    assert not (workspace_root / "api_requires_confirm").exists()


def test_pretrip_import_gpx_run_writes_workspace_and_returns_projection_paths(tmp_path):
    workspace_root = tmp_path / "pretrip_workspace"
    inbox = tmp_path / "inbox"
    reference_dir = inbox / "refs"
    golden_route = inbox / "golden-route.gpx"
    explicit_reference = inbox / "reference-explicit.gpx"
    directory_reference = reference_dir / "reference-dir.gpx"
    _write_small_gpx(
        golden_route,
        name="api run golden route",
        points=[
            (24.0, 121.0, 1000.0),
            (24.006, 121.006, 1010.0),
            (24.012, 121.012, 1020.0),
        ],
    )
    _write_small_gpx(
        explicit_reference,
        name="api run explicit reference",
        points=[(24.0, 121.0, 1000.0), (24.01, 121.01, 1015.0)],
    )
    _write_small_gpx(
        directory_reference,
        name="api run directory reference",
        points=[(24.001, 121.001, 1001.0), (24.011, 121.011, 1016.0)],
    )
    client = TestClient(create_admin_app(pretrip_workspace_root=workspace_root))

    response = client.post(
        "/admin/pretrip/projects/api_run_import/import-gpx",
        json={
            "confirm_import": True,
            "golden_route_gpx": str(golden_route),
            "reference_dir": str(reference_dir),
            "reference_gpx_paths": [str(explicit_reference)],
            "profile": "pi-offline",
            "checkpoint_spacing_m": 500.0,
            "max_reference_display_points": 2,
            "import_timestamp": "2026-05-21T00:00:00+00:00",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    paths = payload["paths"]
    manifest = payload["manifest"]
    assert payload["artifact_kind"] == "pretrip_import_gpx_result"
    assert payload["persisted"] is True
    assert payload["preview"] is False
    assert manifest["inputs"]["golden_route_gpx"]["role"] == "golden_route_reference"
    assert manifest["counts"]["golden_route_count"] == 1
    assert manifest["counts"]["reference_track_count"] == 2
    assert manifest["boundary"]["actual_user_track_available"] is False
    assert manifest["boundary"]["phase1_runtime_mutation_allowed"] is False
    assert manifest["boundary"]["mission_graph_compiled"] is False
    assert payload["boundary"]["runtime_mutation_allowed"] is False
    assert payload["boundary"]["final_mission_graph_compiled"] is False
    assert payload["mutation"]["workspace_import_outputs_mutated"] is True
    assert Path(paths["manifest_path"]).is_file()
    assert Path(paths["admin_projection_path"]).is_file()
    assert Path(paths["debug_projection_events_path"]).is_file()
    assert paths["manifest_path"].endswith("outputs/import_manifest.json")
    assert paths["admin_projection_path"].endswith("outputs/admin_projection.json")
    assert paths["debug_projection_events_path"].endswith(
        "outputs/debug_projection_events.jsonl"
    )
    assert "<trkpt" not in response.text.lower()

    admin_projection = client.get(
        "/admin/pretrip/projects/api_run_import/admin-projection"
    )
    debug_projection = client.get(
        "/admin/pretrip/projects/api_run_import/debug-projection-events"
    )
    debug_projection_view = client.get(
        "/admin/pretrip/projects/api_run_import/debug-projection"
    )
    assert admin_projection.status_code == 200
    assert admin_projection.json()["planning_semantics"][
        "pretrip_actual_user_track_exists"
    ] is False
    assert debug_projection.status_code == 200
    assert debug_projection.json()["event_count"] == 4
    assert debug_projection.json()["boundary"]["phase1_runtime_mutation_allowed"] is False
    assert debug_projection_view.status_code == 200
    debug_projection_payload = debug_projection_view.json()
    assert debug_projection_payload["event_count"] > 4
    assert debug_projection_payload["counts"]["reference_track_count"] == 2
    assert debug_projection_payload["boundary"]["runtime_safety_truth"] is False
    assert debug_projection_payload["timeline_events"][2]["kind"] == "checkpoint_detected"


def test_pretrip_prepare_layers_preview_is_workspace_metadata_only(tmp_path):
    original_fixture_bytes = _repo_fixture_bytes()
    workspace_root = _copy_pretrip_workspace(tmp_path)
    client = TestClient(create_admin_app(pretrip_workspace_root=workspace_root))

    response = client.post(
        f"/admin/pretrip/projects/{PROJECT_ID}/prepare-layers-preview",
        json={
            "layers": ["osm", "overpass", "terrain", "imagery", "weather"],
            "prepared_at": "2026-05-22T00:00:00+00:00",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["artifact_kind"] == "pretrip_layer_preparation_preview_result"
    assert payload["preview"] is True
    assert payload["persisted"] is False
    assert payload["manifest"]["counts"]["layer_count"] == 5
    assert payload["manifest"]["network_policy"]["network_calls_made"] is False
    assert payload["boundary"]["workspace_file_mutation_allowed"] is False
    assert payload["boundary"]["phase1_runtime_mutation_allowed"] is False
    assert payload["mutation"]["workspace_files_mutated"] is False
    assert not (workspace_root / PROJECT_ID / "outputs" / "layers").exists()
    assert "<trkpt" not in response.text.lower()
    assert _repo_fixture_bytes() == original_fixture_bytes


def test_pretrip_prepare_layers_run_writes_workspace_and_feeds_admin_debug(tmp_path):
    workspace_root = _copy_pretrip_workspace(tmp_path)
    client = TestClient(create_admin_app(pretrip_workspace_root=workspace_root))

    rejected = client.post(
        f"/admin/pretrip/projects/{PROJECT_ID}/prepare-layers",
        json={"layers": ["osm", "terrain"]},
    )
    response = client.post(
        f"/admin/pretrip/projects/{PROJECT_ID}/prepare-layers",
        json={
            "confirm_prepare": True,
            "layers": ["osm", "terrain"],
            "prepared_at": "2026-05-22T00:00:00+00:00",
        },
    )
    layer_view_response = client.get(
        f"/admin/pretrip/projects/{PROJECT_ID}/layer-preparation"
    )
    debug_response = client.get(
        f"/admin/pretrip/projects/{PROJECT_ID}/debug-projection-events"
    )

    assert rejected.status_code == 400
    assert response.status_code == 200
    payload = response.json()
    assert payload["artifact_kind"] == "pretrip_layer_preparation_result"
    assert payload["persisted"] is True
    assert payload["manifest"]["counts"]["layer_count"] == 2
    assert payload["manifest"]["boundary"]["phase1_runtime_mutation_allowed"] is False
    assert payload["manifest"]["boundary"]["final_mission_graph_compiled"] is False
    assert payload["mutation"]["workspace_layer_outputs_mutated"] is True
    assert Path(payload["paths"]["manifest_path"]).is_file()

    assert layer_view_response.status_code == 200
    layer_view = layer_view_response.json()
    assert layer_view["status"] == "ready_with_warnings"
    assert layer_view["counts"]["ready_layer_count"] == 2
    assert [layer["layer_id"] for layer in layer_view["layers"]] == ["osm", "terrain"]

    assert debug_response.status_code == 200
    debug_payload = debug_response.json()
    assert debug_payload["event_count"] > 4
    assert debug_payload["layer_source_path"] == (
        "outputs/layers/projections/admin_debug_events.jsonl"
    )


def test_pretrip_review_decision_api_returns_accepted_preview_record():
    original_log = REPO_REVIEW_DECISION_LOG.read_bytes()
    client = TestClient(create_admin_app())

    response = client.post(
        f"/admin/pretrip/projects/{PROJECT_ID}/review-decisions",
        json=_accepted_review_payload(),
    )

    assert response.status_code == 200
    payload = response.json()
    record = payload["record"]
    assert payload["artifact_kind"] == "pretrip_review_decision_preview"
    assert payload["preview"] is True
    assert payload["append_only"] is True
    assert record["decision"] == "accepted"
    assert record["candidate_ref"] == "contour.g11.seg_001_003"
    assert record["draft_action_id"] == (
        "review_draft.chilai_nanhua_day1.contour.contour.g11.seg_001_003"
    )
    assert record["target_ids"] == ["seg.001", "seg.002", "seg.003"]
    assert record["append_only"] is True
    assert record["package_mutation_allowed"] is False
    assert record["runtime_mutation_allowed"] is False
    assert record["phase1_runtime_mutation_allowed"] is False
    assert payload["boundary"]["package_mutation_allowed"] is False
    assert payload["boundary"]["runtime_mutation_allowed"] is False
    assert payload["boundary"]["phase1_runtime_mutation_allowed"] is False
    assert payload["boundary"]["phase2_writeback_allowed"] is False
    assert payload["boundary"]["external_api_calls_made"] is False
    assert payload["boundary"]["fixture_file_mutation_allowed"] is False
    assert payload["boundary"]["admin_api_write_performed"] is False
    assert payload["mutation"] == {
        "source_mutated": False,
        "package_mutated": False,
        "runtime_mutated": False,
        "phase1_runtime_mutated": False,
        "phase2_writeback_performed": False,
        "fixture_files_mutated": False,
    }
    assert REPO_REVIEW_DECISION_LOG.read_bytes() == original_log


def test_pretrip_review_decision_api_rejects_persist_without_workspace():
    original_log = REPO_REVIEW_DECISION_LOG.read_bytes()
    client = TestClient(create_admin_app())

    response = client.post(
        f"/admin/pretrip/projects/{PROJECT_ID}/review-decisions",
        json=_accepted_review_payload(
            candidate_ref=UNDECIDED_CONTOUR_CANDIDATE_REF,
            summary=UNDECIDED_CONTOUR_SUMMARY,
            persist_to_workspace=True,
        ),
    )

    assert response.status_code == 409
    assert "persist_to_workspace requires" in response.json()["detail"]
    assert REPO_REVIEW_DECISION_LOG.read_bytes() == original_log


def test_pretrip_review_decision_api_persists_to_tmp_workspace(tmp_path):
    original_log = REPO_REVIEW_DECISION_LOG.read_bytes()
    workspace_root = _copy_pretrip_workspace(tmp_path)
    workspace_log = workspace_root / PROJECT_ID / "reviews" / "review_decision_log.json"
    client = TestClient(create_admin_app(pretrip_workspace_root=workspace_root))

    response = client.post(
        f"/admin/pretrip/projects/{PROJECT_ID}/review-decisions",
        json=_accepted_review_payload(
            candidate_ref=UNDECIDED_CONTOUR_CANDIDATE_REF,
            summary=UNDECIDED_CONTOUR_SUMMARY,
            persist_to_workspace=True,
        ),
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["artifact_kind"] == "pretrip_review_decision"
    assert payload["preview"] is False
    assert payload["persisted"] is True
    assert payload["counts"]["action_count"] == 4
    assert payload["counts"]["accepted_count"] == 2
    assert payload["record"]["candidate_ref"] == UNDECIDED_CONTOUR_CANDIDATE_REF
    assert payload["record"]["target_ids"] == UNDECIDED_CONTOUR_TARGET_IDS
    assert payload["record"]["source_review_queue_item_refs"] == [
        {
            "review_queue_manifest_id": "review_queue.chilai_nanhua_day1.v0",
            "item_id": (
                "review_queue.chilai_nanhua_day1.contour."
                "contour.g11.seg_006_008"
            ),
            "source_ref": "outputs/contour_interpretation_candidates.json",
            "candidate_ref": UNDECIDED_CONTOUR_CANDIDATE_REF,
        }
    ]
    assert payload["boundary"]["source_mutation_allowed"] is False
    assert payload["boundary"]["package_mutation_allowed"] is False
    assert payload["boundary"]["runtime_mutation_allowed"] is False
    assert payload["boundary"]["phase1_runtime_mutation_allowed"] is False
    assert payload["boundary"]["phase2_writeback_allowed"] is False
    assert payload["boundary"]["admin_api_write_performed"] is True
    assert payload["boundary"]["fixture_file_mutation_allowed"] is False
    assert payload["boundary"]["workspace_file_mutation_allowed"] is True
    assert payload["boundary"]["workspace_review_log_path"] == str(workspace_log)
    assert payload["mutation"]["fixture_files_mutated"] is False
    assert payload["mutation"]["workspace_files_mutated"] is True
    assert payload["mutation"]["workspace_review_log_mutated"] is True

    persisted_log = json.loads(workspace_log.read_text(encoding="utf-8"))
    assert persisted_log["counts"]["action_count"] == 4
    assert persisted_log["counts"]["accepted_count"] == 2
    assert persisted_log["decisions"][-1]["decision_id"] == payload["record"]["decision_id"]
    assert persisted_log["decisions"][-1]["candidate_ref"] == UNDECIDED_CONTOUR_CANDIDATE_REF
    assert persisted_log["decisions"][-1]["target_ids"] == UNDECIDED_CONTOUR_TARGET_IDS
    assert REPO_REVIEW_DECISION_LOG.read_bytes() == original_log


def test_pretrip_route_note_disposition_api_rejects_without_workspace():
    original_fixture_bytes = _repo_fixture_bytes()
    client = TestClient(create_admin_app())

    response = client.post(
        f"/admin/pretrip/projects/{PROJECT_ID}/route-note-dispositions",
        json={
            "route_note_ref": "route_note.rudy_like_gpx.wpt_000",
            "disposition": "promote_hint",
            "persist_to_workspace": True,
        },
    )

    assert response.status_code == 409
    assert "pretrip_workspace_root" in response.json()["detail"]
    assert _repo_fixture_bytes() == original_fixture_bytes


def test_pretrip_route_note_disposition_api_persists_to_tmp_workspace_only(tmp_path):
    original_fixture_bytes = _repo_fixture_bytes()
    workspace_root = _copy_pretrip_workspace(tmp_path)
    workspace_log = (
        workspace_root / PROJECT_ID / "reviews" / "route_note_disposition_log.json"
    )
    client = TestClient(create_admin_app(pretrip_workspace_root=workspace_root))

    response = client.post(
        f"/admin/pretrip/projects/{PROJECT_ID}/route-note-dispositions",
        json={
            "route_note_ref": "route_note.rudy_like_gpx.wpt_000",
            "disposition": "promote_warning",
            "reviewer_alias": "trip_leader",
            "decided_at": "2026-05-15T11:30:00+08:00",
            "persist_to_workspace": True,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["artifact_kind"] == "pretrip_route_note_disposition_log"
    assert payload["persisted"] is True
    assert payload["counts"]["disposition_count"] == 1
    assert payload["counts"]["promote_warning_count"] == 1
    assert payload["record"]["candidate_ref"] == "route_note.rudy_like_gpx.wpt_000"
    assert payload["record"]["selected_disposition"] == "promote_warning"
    assert payload["record"]["metadata_only"] is True
    assert payload["record"]["package_mutation_allowed"] is False
    assert payload["record"]["mission_graph_mutation_allowed"] is False
    assert payload["record"]["runtime_mutation_allowed"] is False
    assert payload["record"]["phase1_runtime_mutation_allowed"] is False
    assert payload["record"]["phase2_writeback_allowed"] is False
    assert payload["record"]["raw_gpx_embedded"] is False
    assert payload["boundary"]["source_mutation_allowed"] is False
    assert payload["boundary"]["package_mutation_allowed"] is False
    assert payload["boundary"]["mission_graph_mutation_allowed"] is False
    assert payload["boundary"]["runtime_mutation_allowed"] is False
    assert payload["boundary"]["phase1_runtime_mutation_allowed"] is False
    assert payload["boundary"]["phase2_writeback_allowed"] is False
    assert payload["boundary"]["external_api_calls_made"] is False
    assert payload["boundary"]["admin_api_write_performed"] is True
    assert payload["boundary"]["fixture_file_mutation_allowed"] is False
    assert payload["boundary"]["workspace_file_mutation_allowed"] is True
    assert payload["boundary"]["compiles_mission_graph"] is False
    assert payload["boundary"]["raw_payloads_embedded"] is False
    assert payload["boundary"]["workspace_route_note_disposition_log_path"] == str(
        workspace_log
    )
    assert payload["mutation"]["fixture_files_mutated"] is False
    assert payload["mutation"]["workspace_files_mutated"] is True
    assert payload["mutation"]["workspace_route_note_disposition_log_mutated"] is True

    persisted_log = json.loads(workspace_log.read_text(encoding="utf-8"))
    assert persisted_log["counts"]["disposition_count"] == 1
    assert persisted_log["records"][0]["candidate_ref"] == "route_note.rudy_like_gpx.wpt_000"
    assert persisted_log["records"][0]["selected_disposition"] == "promote_warning"
    assert "<gpx" not in workspace_log.read_text(encoding="utf-8").lower()
    assert _repo_fixture_bytes() == original_fixture_bytes


def test_pretrip_route_note_disposition_api_rejects_duplicate_workspace_append(
    tmp_path,
):
    workspace_root = _copy_pretrip_workspace(tmp_path)
    workspace_log = (
        workspace_root / PROJECT_ID / "reviews" / "route_note_disposition_log.json"
    )
    client = TestClient(create_admin_app(pretrip_workspace_root=workspace_root))
    payload = {
        "route_note_ref": "route_note.rudy_like_gpx.wpt_000",
        "disposition": "field_verify",
        "persist_to_workspace": True,
    }

    first = client.post(
        f"/admin/pretrip/projects/{PROJECT_ID}/route-note-dispositions",
        json=payload,
    )
    duplicate = client.post(
        f"/admin/pretrip/projects/{PROJECT_ID}/route-note-dispositions",
        json=payload,
    )

    assert first.status_code == 200
    assert duplicate.status_code == 409
    assert "duplicate route-note candidate_ref" in duplicate.json()["detail"]
    persisted_log = json.loads(workspace_log.read_text(encoding="utf-8"))
    assert persisted_log["counts"]["disposition_count"] == 1


def test_pretrip_workspace_edit_api_adds_manual_checkpoint_to_workspace_only(tmp_path):
    original_fixture_bytes = _repo_fixture_bytes()
    workspace_root = _copy_pretrip_workspace(tmp_path)
    workspace_project_root = workspace_root / PROJECT_ID
    workspace_log = workspace_project_root / "reviews" / "workspace_edit_log.json"
    workspace_checkpoints = workspace_project_root / "candidates" / "checkpoints.json"
    workspace_package = workspace_project_root / "outputs" / "pretrip_package.json"
    before_checkpoints = workspace_checkpoints.read_bytes()
    before_package = workspace_package.read_bytes()
    client = TestClient(create_admin_app(pretrip_workspace_root=workspace_root))

    response = client.post(
        f"/admin/pretrip/projects/{PROJECT_ID}/workspace-edits",
        json={
            "operation": "add_checkpoint",
            "summary": "Manual waypoint candidate added from local pretrip map edit.",
            "reviewer_alias": "trip_leader",
            "created_at": "2026-05-21T10:00:00+08:00",
            "candidate": {
                "candidate_id": "manual.cp.water_001",
                "label": "Manual water waypoint",
                "lat": 24.053,
                "lon": 121.231,
                "checkpoint_type": "waypoint",
                "review_state": "needs_human_review",
            },
            "source_refs": ["admin.pretrip.map_click"],
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["artifact_kind"] == "pretrip_workspace_edit_log"
    assert payload["persisted"] is True
    assert payload["append_only"] is True
    assert payload["candidate_only"] is True
    assert payload["counts"]["edit_count"] == 1
    assert payload["counts"]["add_checkpoint_count"] == 1
    assert payload["counts"]["candidate_only_edit_count"] == 1
    assert payload["counts"]["package_mutation_count"] == 0
    assert payload["counts"]["mission_graph_mutation_count"] == 0
    assert payload["counts"]["runtime_mutation_count"] == 0
    assert payload["counts"]["phase1_runtime_mutation_count"] == 0
    assert payload["record"]["operation"] == "add_checkpoint"
    assert payload["record"]["target_kind"] == "checkpoint_waypoint"
    assert payload["record"]["candidate_payload"]["candidate_id"] == (
        "manual.cp.water_001"
    )
    assert payload["record"]["candidate_only"] is True
    assert payload["record"]["candidate_artifact_mutation_allowed"] is False
    assert payload["record"]["package_mutation_allowed"] is False
    assert payload["record"]["mission_graph_mutation_allowed"] is False
    assert payload["record"]["runtime_mutation_allowed"] is False
    assert payload["record"]["phase1_runtime_mutation_allowed"] is False
    assert payload["record"]["phase2_writeback_allowed"] is False
    assert payload["record"]["final_mission_graph_compiled"] is False
    assert payload["boundary"]["local_workspace_only"] is True
    assert payload["boundary"]["candidate_only"] is True
    assert payload["boundary"]["candidate_artifact_mutation_allowed"] is False
    assert payload["boundary"]["workspace_candidate_artifact_mutation_allowed"] is True
    assert payload["boundary"]["package_mutation_allowed"] is False
    assert payload["boundary"]["mission_graph_mutation_allowed"] is False
    assert payload["boundary"]["runtime_mutation_allowed"] is False
    assert payload["boundary"]["phase1_runtime_mutation_allowed"] is False
    assert payload["boundary"]["phase2_writeback_allowed"] is False
    assert payload["boundary"]["compiles_mission_graph"] is False
    assert payload["boundary"]["final_mission_graph_compiled"] is False
    assert payload["boundary"]["external_api_calls_made"] is False
    assert payload["boundary"]["fixture_file_mutation_allowed"] is False
    assert payload["boundary"]["workspace_file_mutation_allowed"] is True
    assert payload["boundary"]["workspace_edit_log_path"] == str(workspace_log)
    assert payload["mutation"]["candidate_artifacts_mutated"] is False
    assert payload["mutation"]["workspace_candidate_artifacts_mutated"] is True
    assert payload["mutation"]["checkpoint_candidates_mutated"] is True
    assert payload["mutation"]["retreat_route_candidates_mutated"] is False
    assert payload["mutation"]["package_mutated"] is False
    assert payload["mutation"]["mission_graph_mutated"] is False
    assert payload["mutation"]["runtime_mutated"] is False
    assert payload["mutation"]["phase1_runtime_mutated"] is False
    assert payload["mutation"]["phase2_writeback_performed"] is False
    assert payload["mutation"]["fixture_files_mutated"] is False
    assert payload["mutation"]["workspace_files_mutated"] is True
    assert payload["mutation"]["workspace_edit_log_mutated"] is True

    persisted_log = json.loads(workspace_log.read_text(encoding="utf-8"))
    assert persisted_log["counts"]["edit_count"] == 1
    assert persisted_log["records"][0]["operation"] == "add_checkpoint"
    assert persisted_log["records"][0]["candidate_payload"]["candidate_id"] == (
        "manual.cp.water_001"
    )
    assert "Final MissionGraph" not in workspace_log.read_text(encoding="utf-8")
    assert "/safety/" not in workspace_log.read_text(encoding="utf-8")
    after_checkpoints = json.loads(workspace_checkpoints.read_text(encoding="utf-8"))
    before_checkpoint_payload = json.loads(before_checkpoints)
    assert len(after_checkpoints) == len(before_checkpoint_payload) + 1
    assert after_checkpoints[-1]["candidate_id"] == "manual.cp.water_001"
    assert after_checkpoints[-1]["review_state"] == "needs_human_review"
    assert workspace_package.read_bytes() == before_package
    assert _repo_fixture_bytes() == original_fixture_bytes


def test_pretrip_workspace_edit_api_records_planned_tool_operations(tmp_path):
    original_fixture_bytes = _repo_fixture_bytes()
    workspace_root = _copy_pretrip_workspace(tmp_path)
    workspace_project_root = workspace_root / PROJECT_ID
    workspace_log = workspace_project_root / "reviews" / "workspace_edit_log.json"
    workspace_checkpoints = workspace_project_root / "candidates" / "checkpoints.json"
    workspace_retreat_routes = (
        workspace_project_root / "candidates" / "retreat_routes.json"
    )
    before_checkpoints = workspace_checkpoints.read_bytes()
    before_retreat_routes = workspace_retreat_routes.read_bytes()
    client = TestClient(create_admin_app(pretrip_workspace_root=workspace_root))

    requests = [
        {
            "operation": "remove_checkpoint",
            "target_ref": "cp.010",
            "summary": "Remove checkpoint candidate from local planning draft.",
        },
        {
            "operation": "add_retreat_route",
            "summary": "Add local retreat route candidate for human review.",
            "candidate": {
                "candidate_id": "retreat.manual.shelter_exit",
                "entry_checkpoint_candidate_id": "cp.010",
                "retreat_type": "alternate_route",
                "expected_use": "retreat",
                "review_state": "needs_human_review",
            },
        },
        {
            "operation": "remove_retreat_route",
            "target_ref": "retreat.chilai_nanhua_day1.return_to_entry",
            "summary": "Remove retreat route candidate from local planning draft.",
        },
        {
            "operation": "feature_edit",
            "target_ref": "overpass.node.shelter_001",
            "field_updates": {
                "review_state": "needs_human_review",
                "label": "Potential shelter feature",
            },
            "summary": "Update local feature candidate fields.",
        },
        {
            "operation": "select_trail_generate_waypoint",
            "target_ref": "overpass.way.trail_001",
            "candidate": {
                "candidate_id": "manual.cp.trail_select_001",
                "label": "Trail-selected waypoint",
                "lat": 24.055,
                "lon": 121.233,
                "review_state": "needs_human_review",
            },
            "summary": "Generate waypoint candidate from selected trail evidence.",
        },
        {
            "operation": "rectangle_group_selection",
            "target_refs": ["cp.011", "cp.012"],
            "selection": {
                "bbox_wgs84": {
                    "min_lat": 24.04,
                    "min_lon": 121.22,
                    "max_lat": 24.06,
                    "max_lon": 121.24,
                }
            },
            "summary": "Record local rectangle group selection.",
        },
    ]

    responses = [
        client.post(
            f"/admin/pretrip/projects/{PROJECT_ID}/workspace-edits",
            json=request,
        )
        for request in requests
    ]

    assert [response.status_code for response in responses] == [200] * len(requests)
    final_payload = responses[-1].json()
    assert final_payload["counts"]["edit_count"] == 6
    assert final_payload["counts"]["remove_checkpoint_count"] == 1
    assert final_payload["counts"]["add_retreat_route_count"] == 1
    assert final_payload["counts"]["remove_retreat_route_count"] == 1
    assert final_payload["counts"]["feature_edit_count"] == 1
    assert final_payload["counts"]["select_trail_generate_waypoint_count"] == 1
    assert final_payload["counts"]["rectangle_group_selection_count"] == 1
    assert final_payload["counts"]["candidate_artifact_mutation_count"] == 0
    assert final_payload["counts"]["package_mutation_count"] == 0
    assert final_payload["counts"]["mission_graph_mutation_count"] == 0
    assert final_payload["counts"]["runtime_mutation_count"] == 0
    assert final_payload["counts"]["phase2_writeback_count"] == 0
    assert final_payload["record"]["operation"] == "rectangle_group_selection"
    assert final_payload["record"]["target_kind"] == "rectangle_selection"
    assert final_payload["boundary"]["workspace_candidate_artifact_mutation_allowed"] is True
    assert final_payload["boundary"]["package_mutation_allowed"] is False
    assert final_payload["boundary"]["mission_graph_mutation_allowed"] is False
    assert final_payload["boundary"]["runtime_mutation_allowed"] is False
    assert final_payload["boundary"]["phase1_runtime_mutation_allowed"] is False
    assert final_payload["boundary"]["phase2_writeback_allowed"] is False
    assert final_payload["boundary"]["final_mission_graph_compiled"] is False

    persisted_log = json.loads(workspace_log.read_text(encoding="utf-8"))
    assert [record["operation"] for record in persisted_log["records"]] == [
        "remove_checkpoint",
        "add_retreat_route",
        "remove_retreat_route",
        "feature_edit",
        "select_trail_generate_waypoint",
        "rectangle_group_selection",
    ]
    assert persisted_log["records"][1]["target_kind"] == "retreat_route"
    assert persisted_log["records"][3]["field_updates"]["label"] == (
        "Potential shelter feature"
    )
    assert responses[0].json()["mutation"]["checkpoint_candidates_mutated"] is True
    assert responses[1].json()["mutation"]["retreat_route_candidates_mutated"] is True
    assert responses[2].json()["mutation"]["retreat_route_candidates_mutated"] is True
    assert responses[3].json()["mutation"]["workspace_candidate_artifacts_mutated"] is False
    assert responses[4].json()["mutation"]["checkpoint_candidates_mutated"] is True
    after_checkpoints = json.loads(workspace_checkpoints.read_text(encoding="utf-8"))
    after_retreat_routes = json.loads(workspace_retreat_routes.read_text(encoding="utf-8"))
    assert workspace_checkpoints.read_bytes() != before_checkpoints
    assert workspace_retreat_routes.read_bytes() != before_retreat_routes
    assert all(item["candidate_id"] != "cp.010" for item in after_checkpoints)
    assert any(
        item["candidate_id"] == "manual.cp.trail_select_001"
        for item in after_checkpoints
    )
    assert all(
        item["candidate_id"] != "retreat.chilai_nanhua_day1.return_to_entry"
        for item in after_retreat_routes
    )
    assert any(
        item["candidate_id"] == "retreat.manual.shelter_exit"
        for item in after_retreat_routes
    )
    assert _repo_fixture_bytes() == original_fixture_bytes


def test_pretrip_workspace_edit_api_rejects_without_workspace():
    original_fixture_bytes = _repo_fixture_bytes()
    client = TestClient(create_admin_app())

    response = client.post(
        f"/admin/pretrip/projects/{PROJECT_ID}/workspace-edits",
        json={
            "operation": "remove_checkpoint",
            "target_ref": "cp.010",
            "summary": "Remove checkpoint candidate from local planning draft.",
        },
    )

    assert response.status_code == 409
    assert "pretrip_workspace_root" in response.json()["detail"]
    assert _repo_fixture_bytes() == original_fixture_bytes


def test_pretrip_workspace_edit_api_rejects_repo_fixture_root():
    original_fixture_bytes = _repo_fixture_bytes()
    client = TestClient(create_admin_app(pretrip_workspace_root=FIXTURE_PROJECT_ROOT))

    response = client.post(
        f"/admin/pretrip/projects/{PROJECT_ID}/workspace-edits",
        json={
            "operation": "remove_checkpoint",
            "target_ref": "cp.010",
            "summary": "Remove checkpoint candidate from local planning draft.",
        },
    )

    assert response.status_code == 409
    assert "copied workspace, not repo fixtures" in response.json()["detail"]
    assert _repo_fixture_bytes() == original_fixture_bytes


def test_pretrip_route_note_reviewed_assumptions_api_rejects_without_workspace():
    original_fixture_bytes = _repo_fixture_bytes()
    client = TestClient(create_admin_app())

    response = client.post(
        f"/admin/pretrip/projects/{PROJECT_ID}/route-note-reviewed-assumptions"
    )

    assert response.status_code == 409
    assert "pretrip_workspace_root" in response.json()["detail"]
    assert _repo_fixture_bytes() == original_fixture_bytes


def test_pretrip_route_note_reviewed_assumptions_api_writes_workspace_only(tmp_path):
    original_fixture_bytes = _repo_fixture_bytes()
    workspace_root = _copy_pretrip_workspace(tmp_path)
    workspace_assumptions = (
        workspace_root / PROJECT_ID / "outputs" / "route_note_reviewed_assumptions.json"
    )
    client = TestClient(create_admin_app(pretrip_workspace_root=workspace_root))

    disposition_response = client.post(
        f"/admin/pretrip/projects/{PROJECT_ID}/route-note-dispositions",
        json={
            "route_note_ref": "route_note.rudy_like_gpx.wpt_000",
            "disposition": "promote_warning",
            "reviewer_alias": "trip_leader",
            "decided_at": "2026-05-15T11:30:00+08:00",
            "persist_to_workspace": True,
        },
    )
    response = client.post(
        f"/admin/pretrip/projects/{PROJECT_ID}/route-note-reviewed-assumptions"
    )

    assert disposition_response.status_code == 200
    assert response.status_code == 200
    payload = response.json()
    assert payload["artifact_kind"] == "pretrip_route_note_reviewed_assumptions"
    assert payload["persisted"] is True
    assert payload["counts"]["disposition_count"] == 1
    assert payload["counts"]["accepted_interpretation_count"] == 1
    assert payload["counts"]["ln_expansion_candidate_count"] == 1
    assert payload["counts"]["warning_expansion_candidate_count"] == 1
    assert payload["counts"]["runtime_activation_count"] == 0
    assert payload["counts"]["phase2_writeback_count"] == 0
    assert payload["boundary"]["package_mutation_allowed"] is False
    assert payload["boundary"]["mission_graph_mutation_allowed"] is False
    assert payload["boundary"]["runtime_mutation_allowed"] is False
    assert payload["boundary"]["phase1_runtime_mutation_allowed"] is False
    assert payload["boundary"]["phase2_writeback_allowed"] is False
    assert payload["boundary"]["fixture_file_mutation_allowed"] is False
    assert payload["boundary"]["workspace_file_mutation_allowed"] is True
    assert payload["boundary"]["workspace_route_note_reviewed_assumptions_path"] == str(
        workspace_assumptions
    )
    assert payload["mutation"]["workspace_route_note_reviewed_assumptions_mutated"] is True
    assert workspace_assumptions.is_file()
    workspace_payload = json.loads(workspace_assumptions.read_text(encoding="utf-8"))
    assert workspace_payload["counts"]["accepted_interpretation_count"] == 1
    assert not REPO_ROUTE_NOTE_REVIEWED_ASSUMPTIONS.exists()
    assert _repo_fixture_bytes() == original_fixture_bytes


def test_pretrip_project_api_overlays_route_note_reviewed_assumptions(tmp_path):
    workspace_root = _copy_pretrip_workspace(tmp_path)
    client = TestClient(create_admin_app(pretrip_workspace_root=workspace_root))

    disposition_response = client.post(
        f"/admin/pretrip/projects/{PROJECT_ID}/route-note-dispositions",
        json={
            "route_note_ref": "route_note.rudy_like_gpx.wpt_000",
            "disposition": "promote_warning",
            "persist_to_workspace": True,
        },
    )
    assumptions_response = client.post(
        f"/admin/pretrip/projects/{PROJECT_ID}/route-note-reviewed-assumptions"
    )
    view_response = client.get(f"/admin/pretrip/projects/{PROJECT_ID}")

    assert disposition_response.status_code == 200
    assert assumptions_response.status_code == 200
    assert view_response.status_code == 200
    view = view_response.json()
    assumptions = view["route_note_reviewed_assumptions"]
    assert assumptions["counts"]["accepted_interpretation_count"] == 1
    assert assumptions["counts"]["ln_expansion_candidate_count"] == 1
    assert assumptions["boundary"]["runtime_activation_allowed"] is False
    sections = {
        section["id"]: section
        for section in view["tabs"]["review_workspace"]["sections"]
    }
    assert sections["route_note_reviewed_assumptions"]["counts"][
        "accepted_interpretation_count"
    ] == 1


def test_pretrip_project_api_overlays_local_workspace_review_decisions(tmp_path):
    original_log = REPO_REVIEW_DECISION_LOG.read_bytes()
    workspace_root = tmp_path / "pretrip_workspace"
    client = TestClient(create_admin_app(pretrip_workspace_root=workspace_root))

    before_workspace = client.get(f"/admin/pretrip/projects/{PROJECT_ID}")
    workspace_response = client.post(f"/admin/pretrip/projects/{PROJECT_ID}/workspace")
    review_response = client.post(
        f"/admin/pretrip/projects/{PROJECT_ID}/review-decisions",
        json=_accepted_review_payload(
            candidate_ref=UNDECIDED_CONTOUR_CANDIDATE_REF,
            summary=UNDECIDED_CONTOUR_SUMMARY,
            persist_to_workspace=True,
        ),
    )
    after_workspace = client.get(f"/admin/pretrip/projects/{PROJECT_ID}")

    assert before_workspace.status_code == 200
    assert workspace_response.status_code == 200
    assert review_response.status_code == 200
    assert after_workspace.status_code == 200
    before_payload = before_workspace.json()
    after_payload = after_workspace.json()
    assert before_payload["review_decision_log"]["counts"]["action_count"] == 3
    assert after_payload["review_decision_log"]["counts"]["action_count"] == 4
    assert after_payload["review_decision_log"]["counts"]["accepted_count"] == 2
    assert after_payload["review_decision_log"]["source_path"] == (
        "reviews/review_decision_log.json"
    )
    assert after_payload["review_decision_log"]["decisions"][-1]["candidate_ref"] == (
        UNDECIDED_CONTOUR_CANDIDATE_REF
    )
    assert (
        after_payload["tabs"]["pre_trip_planning"]["review_decision_log"][
            "counts"
        ]["action_count"]
        == 4
    )
    assert REPO_REVIEW_DECISION_LOG.read_bytes() == original_log


def test_pretrip_review_decision_api_rejects_duplicate_workspace_append(tmp_path):
    original_log = REPO_REVIEW_DECISION_LOG.read_bytes()
    workspace_root = _copy_pretrip_workspace(tmp_path)
    workspace_log = workspace_root / PROJECT_ID / "reviews" / "review_decision_log.json"
    client = TestClient(create_admin_app(pretrip_workspace_root=workspace_root))

    first_response = client.post(
        f"/admin/pretrip/projects/{PROJECT_ID}/review-decisions",
        json=_accepted_review_payload(
            candidate_ref=UNDECIDED_CONTOUR_CANDIDATE_REF,
            summary=UNDECIDED_CONTOUR_SUMMARY,
            persist_to_workspace=True,
        ),
    )
    duplicate_response = client.post(
        f"/admin/pretrip/projects/{PROJECT_ID}/review-decisions",
        json=_accepted_review_payload(
            candidate_ref=UNDECIDED_CONTOUR_CANDIDATE_REF,
            summary=UNDECIDED_CONTOUR_SUMMARY,
            persist_to_workspace=True,
        ),
    )

    assert first_response.status_code == 200
    assert duplicate_response.status_code == 409
    assert "duplicate review decision_id" in duplicate_response.json()["detail"]
    persisted_log = json.loads(workspace_log.read_text(encoding="utf-8"))
    assert persisted_log["counts"]["action_count"] == 4
    assert persisted_log["counts"]["accepted_count"] == 2
    assert persisted_log["decisions"][-1]["candidate_ref"] == UNDECIDED_CONTOUR_CANDIDATE_REF
    assert persisted_log["decisions"][-1]["target_ids"] == UNDECIDED_CONTOUR_TARGET_IDS
    assert REPO_REVIEW_DECISION_LOG.read_bytes() == original_log


def test_pretrip_review_decision_api_rejects_duplicate_candidate_ref_append(tmp_path):
    original_log = REPO_REVIEW_DECISION_LOG.read_bytes()
    workspace_root = tmp_path / "pretrip_workspace"
    workspace_project_root = workspace_root / PROJECT_ID
    workspace_log = workspace_project_root / "reviews" / "review_decision_log.json"
    client = TestClient(create_admin_app(pretrip_workspace_root=workspace_root))

    workspace_response = client.post(f"/admin/pretrip/projects/{PROJECT_ID}/workspace")
    first_response = client.post(
        f"/admin/pretrip/projects/{PROJECT_ID}/review-decisions",
        json=_accepted_review_payload(
            candidate_ref=UNDECIDED_CONTOUR_CANDIDATE_REF,
            summary=UNDECIDED_CONTOUR_SUMMARY,
            persist_to_workspace=True,
        ),
    )
    duplicate_response = client.post(
        f"/admin/pretrip/projects/{PROJECT_ID}/review-decisions",
        json=_rejected_review_payload(
            candidate_ref=UNDECIDED_CONTOUR_CANDIDATE_REF,
            summary="Rejected duplicate candidate review decision.",
            persist_to_workspace=True,
        ),
    )

    assert workspace_response.status_code == 200
    assert first_response.status_code == 200
    assert duplicate_response.status_code == 409
    assert "duplicate candidate_ref" in duplicate_response.json()["detail"]
    persisted_log = json.loads(workspace_log.read_text(encoding="utf-8"))
    assert persisted_log["counts"]["action_count"] == 4
    assert persisted_log["counts"]["accepted_count"] == 2
    assert persisted_log["counts"]["rejected_count"] == 1
    assert persisted_log["decisions"][-1]["decision"] == "accepted"


def test_pretrip_review_decision_batch_preview_is_no_write():
    original_log = REPO_REVIEW_DECISION_LOG.read_bytes()
    client = TestClient(create_admin_app())

    response = client.post(
        f"/admin/pretrip/projects/{PROJECT_ID}/review-decisions-batch",
        json=_batch_review_payload(
            _accepted_review_payload(
                candidate_ref=UNDECIDED_CONTOUR_CANDIDATE_REF,
                summary=UNDECIDED_CONTOUR_SUMMARY,
            ),
            _rejected_review_payload(
                candidate_ref=UNDECIDED_DEPARTURE_BUNDLE_CANDIDATE_REF,
                summary=UNDECIDED_DEPARTURE_BUNDLE_SUMMARY,
            ),
        ),
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["artifact_kind"] == "pretrip_review_decision_batch_preview"
    assert payload["preview"] is True
    assert payload["record_count"] == 2
    assert payload["records"][0]["candidate_ref"] == UNDECIDED_CONTOUR_CANDIDATE_REF
    assert payload["records"][1]["candidate_ref"] == UNDECIDED_DEPARTURE_BUNDLE_CANDIDATE_REF
    assert payload["boundary"]["batch_atomic_validation"] is True
    assert payload["boundary"]["admin_api_write_performed"] is False
    assert payload["mutation"]["fixture_files_mutated"] is False
    assert REPO_REVIEW_DECISION_LOG.read_bytes() == original_log


def test_pretrip_review_decision_batch_persists_workspace_atomically(tmp_path):
    original_log = REPO_REVIEW_DECISION_LOG.read_bytes()
    workspace_root = _copy_pretrip_workspace(tmp_path)
    workspace_log = workspace_root / PROJECT_ID / "reviews" / "review_decision_log.json"
    client = TestClient(create_admin_app(pretrip_workspace_root=workspace_root))

    response = client.post(
        f"/admin/pretrip/projects/{PROJECT_ID}/review-decisions-batch",
        json=_batch_review_payload(
            _accepted_review_payload(
                candidate_ref=UNDECIDED_CONTOUR_CANDIDATE_REF,
                summary=UNDECIDED_CONTOUR_SUMMARY,
            ),
            _rejected_review_payload(
                candidate_ref=UNDECIDED_DEPARTURE_BUNDLE_CANDIDATE_REF,
                summary=UNDECIDED_DEPARTURE_BUNDLE_SUMMARY,
            ),
            persist_to_workspace=True,
        ),
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["artifact_kind"] == "pretrip_review_decision_batch"
    assert payload["preview"] is False
    assert payload["persisted"] is True
    assert payload["record_count"] == 2
    assert payload["counts"]["action_count"] == 5
    assert payload["counts"]["accepted_count"] == 2
    assert payload["counts"]["rejected_count"] == 2
    assert payload["boundary"]["workspace_file_mutation_allowed"] is True
    assert payload["boundary"]["workspace_review_log_path"] == str(workspace_log)
    assert payload["mutation"]["workspace_review_log_mutated"] is True

    persisted_log = json.loads(workspace_log.read_text(encoding="utf-8"))
    assert persisted_log["counts"]["action_count"] == 5
    assert persisted_log["decisions"][-2]["candidate_ref"] == UNDECIDED_CONTOUR_CANDIDATE_REF
    assert persisted_log["decisions"][-1]["candidate_ref"] == (
        UNDECIDED_DEPARTURE_BUNDLE_CANDIDATE_REF
    )
    assert REPO_REVIEW_DECISION_LOG.read_bytes() == original_log


def test_pretrip_review_decision_batch_rejects_duplicates_without_partial_write(tmp_path):
    original_log = REPO_REVIEW_DECISION_LOG.read_bytes()
    workspace_root = _copy_pretrip_workspace(tmp_path)
    workspace_log = workspace_root / PROJECT_ID / "reviews" / "review_decision_log.json"
    before_workspace_log = workspace_log.read_bytes()
    client = TestClient(create_admin_app(pretrip_workspace_root=workspace_root))

    response = client.post(
        f"/admin/pretrip/projects/{PROJECT_ID}/review-decisions-batch",
        json=_batch_review_payload(
            _accepted_review_payload(
                candidate_ref=UNDECIDED_CONTOUR_CANDIDATE_REF,
                summary=UNDECIDED_CONTOUR_SUMMARY,
            ),
            _rejected_review_payload(
                candidate_ref=UNDECIDED_CONTOUR_CANDIDATE_REF,
                summary="Rejected duplicate candidate review decision.",
            ),
            persist_to_workspace=True,
        ),
    )

    assert response.status_code == 409
    assert "duplicate candidate_ref" in response.json()["detail"]
    assert workspace_log.read_bytes() == before_workspace_log
    assert REPO_REVIEW_DECISION_LOG.read_bytes() == original_log


def test_pretrip_review_decision_api_validates_against_workspace_queue(tmp_path):
    workspace_root = _copy_pretrip_workspace(tmp_path)
    workspace_queue = (
        workspace_root / PROJECT_ID / "outputs" / "review_queue_manifest.json"
    )
    queue_payload = json.loads(workspace_queue.read_text(encoding="utf-8"))
    queue_payload["items"] = [
        item
        for item in queue_payload["items"]
        if item["candidate_ref"] != UNDECIDED_CONTOUR_CANDIDATE_REF
    ]
    queue_payload["counts"]["item_count"] = len(queue_payload["items"])
    workspace_queue.write_text(
        json.dumps(queue_payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    client = TestClient(create_admin_app(pretrip_workspace_root=workspace_root))

    response = client.post(
        f"/admin/pretrip/projects/{PROJECT_ID}/review-decisions",
        json=_accepted_review_payload(
            candidate_ref=UNDECIDED_CONTOUR_CANDIDATE_REF,
            summary=UNDECIDED_CONTOUR_SUMMARY,
            persist_to_workspace=True,
        ),
    )

    assert response.status_code == 422
    assert "candidate_ref is not in the review queue" in response.json()["detail"]


def test_pretrip_review_decision_apply_plan_api_rejects_without_workspace():
    original_apply_plan = REPO_REVIEW_DECISION_APPLY_PLAN.read_bytes()
    client = TestClient(create_admin_app())

    response = client.post(
        f"/admin/pretrip/projects/{PROJECT_ID}/review-decision-apply-plan"
    )

    assert response.status_code == 409
    assert "pretrip_workspace_root" in response.json()["detail"]
    assert REPO_REVIEW_DECISION_APPLY_PLAN.read_bytes() == original_apply_plan


def test_pretrip_review_decision_apply_plan_api_regenerates_tmp_workspace_only(tmp_path):
    original_apply_plan = REPO_REVIEW_DECISION_APPLY_PLAN.read_bytes()
    workspace_root = _copy_pretrip_workspace(tmp_path)
    workspace_apply_plan = (
        workspace_root / PROJECT_ID / "outputs" / "review_decision_apply_plan.json"
    )
    client = TestClient(create_admin_app(pretrip_workspace_root=workspace_root))

    append_response = client.post(
        f"/admin/pretrip/projects/{PROJECT_ID}/review-decisions",
        json=_accepted_review_payload(
            candidate_ref=UNDECIDED_CONTOUR_CANDIDATE_REF,
            summary=UNDECIDED_CONTOUR_SUMMARY,
            persist_to_workspace=True,
        ),
    )
    response = client.post(
        f"/admin/pretrip/projects/{PROJECT_ID}/review-decision-apply-plan"
    )

    assert append_response.status_code == 200
    assert response.status_code == 200
    payload = response.json()
    assert payload["artifact_kind"] == "pretrip_review_decision_apply_plan"
    assert payload["persisted"] is True
    assert payload["counts"] == {
        "decision_count": 4,
        "accepted": 2,
        "corrected": 1,
        "rejected": 1,
        "source_ref_count": 3,
        "package_candidate_apply_count": 0,
        "runtime_mutation_count": 0,
    }
    assert payload["boundary"]["source_mutation_allowed"] is False
    assert payload["boundary"]["package_mutation_allowed"] is False
    assert payload["boundary"]["runtime_mutation_allowed"] is False
    assert payload["boundary"]["phase1_runtime_mutation_allowed"] is False
    assert payload["boundary"]["phase2_writeback_allowed"] is False
    assert payload["boundary"]["external_api_calls_made"] is False
    assert payload["boundary"]["fixture_file_mutation_allowed"] is False
    assert payload["boundary"]["workspace_file_mutation_allowed"] is True
    assert payload["boundary"]["workspace_apply_plan_path"] == str(workspace_apply_plan)
    assert payload["mutation"]["source_mutated"] is False
    assert payload["mutation"]["package_mutated"] is False
    assert payload["mutation"]["runtime_mutated"] is False
    assert payload["mutation"]["phase1_runtime_mutated"] is False
    assert payload["mutation"]["phase2_writeback_performed"] is False
    assert payload["mutation"]["fixture_files_mutated"] is False
    assert payload["mutation"]["workspace_files_mutated"] is True
    assert payload["mutation"]["workspace_review_decision_apply_plan_mutated"] is True

    workspace_payload = json.loads(workspace_apply_plan.read_text(encoding="utf-8"))
    repo_fixture_payload = json.loads(
        REPO_REVIEW_DECISION_APPLY_PLAN.read_text(encoding="utf-8")
    )
    assert workspace_payload["counts"]["decision_count"] == 4
    assert workspace_payload["decisions"][-1]["candidate_ref"] == (
        UNDECIDED_CONTOUR_CANDIDATE_REF
    )
    assert workspace_payload["decisions"][-1]["target_ids"] == (
        UNDECIDED_CONTOUR_TARGET_IDS
    )
    assert repo_fixture_payload["counts"]["decision_count"] == 3
    assert REPO_REVIEW_DECISION_APPLY_PLAN.read_bytes() == original_apply_plan


def test_pretrip_review_decision_api_persists_gis_cp_workspace_pointer(tmp_path):
    original_review_log = REPO_REVIEW_DECISION_LOG.read_bytes()
    original_apply_plan = REPO_REVIEW_DECISION_APPLY_PLAN.read_bytes()
    workspace_root = tmp_path / "pretrip_workspace"
    workspace_project_root = workspace_root / PROJECT_ID
    workspace_review_log = (
        workspace_project_root / "reviews" / "review_decision_log.json"
    )
    workspace_apply_plan = (
        workspace_project_root / "outputs" / "review_decision_apply_plan.json"
    )
    client = TestClient(create_admin_app(pretrip_workspace_root=workspace_root))

    workspace_response = client.post(f"/admin/pretrip/projects/{PROJECT_ID}/workspace")
    project_response = client.get(f"/admin/pretrip/projects/{PROJECT_ID}")
    project_payload = project_response.json()
    gis_item = next(
        item
        for item in project_payload["review_queue"]["items"]
        if item["category"] == "gis_perception_cp"
    )
    review_response = client.post(
        f"/admin/pretrip/projects/{PROJECT_ID}/review-decisions",
        json=_accepted_review_payload(
            candidate_ref=gis_item["candidate_ref"],
            summary="Accepted GIS CP as candidate-only workspace planning evidence.",
            persist_to_workspace=True,
        ),
    )
    apply_plan_response = client.post(
        f"/admin/pretrip/projects/{PROJECT_ID}/review-decision-apply-plan"
    )

    assert workspace_response.status_code == 200
    assert project_response.status_code == 200
    assert review_response.status_code == 200
    assert apply_plan_response.status_code == 200

    review_payload = review_response.json()
    apply_plan_payload = apply_plan_response.json()
    assert review_payload["record"]["candidate_ref"] == gis_item["candidate_ref"]
    assert review_payload["record"]["target_ids"] == gis_item["review_focus"]
    assert review_payload["record"]["source_review_queue_item_refs"] == [
        {
            "review_queue_manifest_id": "review_queue.chilai_nanhua_day1.v0",
            "item_id": gis_item["item_id"],
            "source_ref": gis_item["source_ref"],
            "candidate_ref": gis_item["candidate_ref"],
        }
    ]
    assert review_payload["boundary"]["package_mutation_allowed"] is False
    assert review_payload["boundary"]["runtime_mutation_allowed"] is False
    assert review_payload["boundary"]["phase1_runtime_mutation_allowed"] is False
    assert review_payload["boundary"]["phase2_writeback_allowed"] is False
    assert apply_plan_payload["counts"]["decision_count"] == 4
    assert apply_plan_payload["counts"]["accepted"] == 2
    assert apply_plan_payload["counts"]["package_candidate_apply_count"] == 0
    assert apply_plan_payload["counts"]["runtime_mutation_count"] == 0

    workspace_review_payload = json.loads(
        workspace_review_log.read_text(encoding="utf-8")
    )
    workspace_apply_payload = json.loads(
        workspace_apply_plan.read_text(encoding="utf-8")
    )
    gis_decision = workspace_apply_payload["decisions"][-1]
    assert workspace_review_payload["decisions"][-1]["candidate_ref"] == (
        gis_item["candidate_ref"]
    )
    assert gis_decision["candidate_ref"] == gis_item["candidate_ref"]
    assert gis_decision["target_ids"] == gis_item["review_focus"]
    assert gis_decision["source_refs"] == [gis_item["source_ref"]]
    assert gis_decision["candidate_application_scope"] == "gis_perception_cp"
    assert gis_decision["candidate_only_review"] is True
    assert gis_decision["runtime_safety_truth"] is False
    assert gis_decision["would_apply_to_package"] is False
    assert gis_decision["package_candidate_apply_count"] == 0
    assert "GIS perception CP decision" in gis_decision["notes"][0]
    assert REPO_REVIEW_DECISION_LOG.read_bytes() == original_review_log
    assert REPO_REVIEW_DECISION_APPLY_PLAN.read_bytes() == original_apply_plan


def test_pretrip_workspace_review_flow_regenerates_workspace_apply_plan_only(tmp_path):
    original_review_log = REPO_REVIEW_DECISION_LOG.read_bytes()
    original_apply_plan = REPO_REVIEW_DECISION_APPLY_PLAN.read_bytes()
    workspace_root = tmp_path / "pretrip_workspace"
    workspace_project_root = workspace_root / PROJECT_ID
    workspace_review_log = (
        workspace_project_root / "reviews" / "review_decision_log.json"
    )
    workspace_apply_plan = (
        workspace_project_root / "outputs" / "review_decision_apply_plan.json"
    )
    client = TestClient(create_admin_app(pretrip_workspace_root=workspace_root))

    workspace_response = client.post(f"/admin/pretrip/projects/{PROJECT_ID}/workspace")
    review_response = client.post(
        f"/admin/pretrip/projects/{PROJECT_ID}/review-decisions",
        json=_accepted_review_payload(
            candidate_ref=UNDECIDED_CONTOUR_CANDIDATE_REF,
            summary=UNDECIDED_CONTOUR_SUMMARY,
            persist_to_workspace=True,
        ),
    )
    apply_plan_response = client.post(
        f"/admin/pretrip/projects/{PROJECT_ID}/review-decision-apply-plan"
    )

    assert workspace_response.status_code == 200
    assert review_response.status_code == 200
    assert apply_plan_response.status_code == 200

    workspace_payload = workspace_response.json()
    review_payload = review_response.json()
    apply_plan_payload = apply_plan_response.json()
    assert workspace_payload["artifact_kind"] == "pretrip_workspace_copy"
    assert workspace_payload["persisted"] is True
    assert workspace_payload["manifest"]["raw_file_count"] == 0
    assert workspace_payload["boundary"]["workspace_project_root"] == str(
        workspace_project_root.resolve()
    )

    assert review_payload["artifact_kind"] == "pretrip_review_decision"
    assert review_payload["preview"] is False
    assert review_payload["persisted"] is True
    assert review_payload["counts"]["action_count"] == 4
    assert review_payload["counts"]["accepted_count"] == 2
    assert review_payload["record"]["candidate_ref"] == UNDECIDED_CONTOUR_CANDIDATE_REF
    assert review_payload["record"]["target_ids"] == UNDECIDED_CONTOUR_TARGET_IDS
    assert review_payload["boundary"]["workspace_review_log_path"] == str(
        workspace_review_log
    )

    assert apply_plan_payload["artifact_kind"] == "pretrip_review_decision_apply_plan"
    assert apply_plan_payload["persisted"] is True
    assert apply_plan_payload["counts"]["decision_count"] == 4
    assert apply_plan_payload["boundary"]["workspace_apply_plan_path"] == str(
        workspace_apply_plan
    )

    for payload in (workspace_payload, review_payload, apply_plan_payload):
        assert payload["boundary"]["source_mutation_allowed"] is False
        assert payload["boundary"]["package_mutation_allowed"] is False
        assert payload["boundary"]["runtime_mutation_allowed"] is False
        assert payload["boundary"]["phase1_runtime_mutation_allowed"] is False
        assert payload["boundary"]["phase2_writeback_allowed"] is False
        assert payload["boundary"]["external_api_calls_made"] is False
        assert payload["boundary"]["fixture_file_mutation_allowed"] is False
        assert payload["boundary"]["workspace_file_mutation_allowed"] is True
        assert payload["mutation"]["source_mutated"] is False
        assert payload["mutation"]["package_mutated"] is False
        assert payload["mutation"]["runtime_mutated"] is False
        assert payload["mutation"]["phase1_runtime_mutated"] is False
        assert payload["mutation"]["phase2_writeback_performed"] is False
        assert payload["mutation"]["fixture_files_mutated"] is False
        assert payload["mutation"]["workspace_files_mutated"] is True

    workspace_review_payload = json.loads(
        workspace_review_log.read_text(encoding="utf-8")
    )
    workspace_apply_payload = json.loads(
        workspace_apply_plan.read_text(encoding="utf-8")
    )
    repo_apply_payload = json.loads(
        REPO_REVIEW_DECISION_APPLY_PLAN.read_text(encoding="utf-8")
    )
    assert workspace_review_payload["counts"]["action_count"] == 4
    assert workspace_review_payload["counts"]["accepted_count"] == 2
    assert workspace_review_payload["decisions"][-1]["candidate_ref"] == (
        UNDECIDED_CONTOUR_CANDIDATE_REF
    )
    assert workspace_review_payload["decisions"][-1]["target_ids"] == (
        UNDECIDED_CONTOUR_TARGET_IDS
    )
    assert workspace_apply_payload["counts"]["decision_count"] == 4
    assert workspace_apply_payload["decisions"][-1]["candidate_ref"] == (
        UNDECIDED_CONTOUR_CANDIDATE_REF
    )
    assert workspace_apply_payload["decisions"][-1]["target_ids"] == (
        UNDECIDED_CONTOUR_TARGET_IDS
    )
    assert repo_apply_payload["counts"]["decision_count"] == 3
    assert REPO_REVIEW_DECISION_LOG.read_bytes() == original_review_log
    assert REPO_REVIEW_DECISION_APPLY_PLAN.read_bytes() == original_apply_plan


def test_pretrip_workspace_rejected_review_flow_regenerates_workspace_apply_plan_only(
    tmp_path,
):
    original_review_log = REPO_REVIEW_DECISION_LOG.read_bytes()
    original_apply_plan = REPO_REVIEW_DECISION_APPLY_PLAN.read_bytes()
    workspace_root = tmp_path / "pretrip_workspace"
    workspace_project_root = workspace_root / PROJECT_ID
    workspace_review_log = (
        workspace_project_root / "reviews" / "review_decision_log.json"
    )
    workspace_apply_plan = (
        workspace_project_root / "outputs" / "review_decision_apply_plan.json"
    )
    client = TestClient(create_admin_app(pretrip_workspace_root=workspace_root))

    workspace_response = client.post(f"/admin/pretrip/projects/{PROJECT_ID}/workspace")
    review_response = client.post(
        f"/admin/pretrip/projects/{PROJECT_ID}/review-decisions",
        json=_rejected_review_payload(
            candidate_ref=UNDECIDED_DEPARTURE_BUNDLE_CANDIDATE_REF,
            summary=UNDECIDED_DEPARTURE_BUNDLE_SUMMARY,
            persist_to_workspace=True,
        ),
    )
    apply_plan_response = client.post(
        f"/admin/pretrip/projects/{PROJECT_ID}/review-decision-apply-plan"
    )

    assert workspace_response.status_code == 200
    assert review_response.status_code == 200
    assert apply_plan_response.status_code == 200

    review_payload = review_response.json()
    apply_plan_payload = apply_plan_response.json()
    assert review_payload["artifact_kind"] == "pretrip_review_decision"
    assert review_payload["preview"] is False
    assert review_payload["persisted"] is True
    assert review_payload["counts"]["action_count"] == 4
    assert review_payload["counts"]["accepted_count"] == 1
    assert review_payload["counts"]["rejected_count"] == 2
    assert review_payload["record"]["decision"] == "rejected"
    assert review_payload["record"]["candidate_ref"] == (
        UNDECIDED_DEPARTURE_BUNDLE_CANDIDATE_REF
    )
    assert review_payload["record"]["target_ids"] == (
        UNDECIDED_DEPARTURE_BUNDLE_TARGET_IDS
    )
    assert review_payload["record"]["source_review_queue_item_refs"] == [
        {
            "review_queue_manifest_id": "review_queue.chilai_nanhua_day1.v0",
            "item_id": (
                "review_queue.chilai_nanhua_day1.departure_bundle."
                "departure_bundle.chilai_nanhua_day1.v0"
            ),
            "source_ref": "outputs/departure_bundle_manifest.json",
            "candidate_ref": UNDECIDED_DEPARTURE_BUNDLE_CANDIDATE_REF,
        }
    ]

    assert apply_plan_payload["artifact_kind"] == "pretrip_review_decision_apply_plan"
    assert apply_plan_payload["persisted"] is True
    assert apply_plan_payload["counts"]["decision_count"] == 4
    assert apply_plan_payload["counts"]["accepted"] == 1
    assert apply_plan_payload["counts"]["rejected"] == 2

    for payload in (review_payload, apply_plan_payload):
        assert payload["boundary"]["package_mutation_allowed"] is False
        assert payload["boundary"]["runtime_mutation_allowed"] is False
        assert payload["boundary"]["phase1_runtime_mutation_allowed"] is False
        assert payload["boundary"]["phase2_writeback_allowed"] is False
        assert payload["boundary"]["fixture_file_mutation_allowed"] is False
        assert payload["mutation"]["package_mutated"] is False
        assert payload["mutation"]["runtime_mutated"] is False
        assert payload["mutation"]["phase1_runtime_mutated"] is False
        assert payload["mutation"]["phase2_writeback_performed"] is False
        assert payload["mutation"]["fixture_files_mutated"] is False
        assert payload["mutation"]["workspace_files_mutated"] is True

    workspace_review_payload = json.loads(
        workspace_review_log.read_text(encoding="utf-8")
    )
    workspace_apply_payload = json.loads(
        workspace_apply_plan.read_text(encoding="utf-8")
    )
    assert workspace_review_payload["counts"]["action_count"] == 4
    assert workspace_review_payload["counts"]["accepted_count"] == 1
    assert workspace_review_payload["counts"]["rejected_count"] == 2
    assert workspace_review_payload["decisions"][-1]["decision"] == "rejected"
    assert workspace_review_payload["decisions"][-1]["candidate_ref"] == (
        UNDECIDED_DEPARTURE_BUNDLE_CANDIDATE_REF
    )
    assert workspace_review_payload["decisions"][-1]["target_ids"] == (
        UNDECIDED_DEPARTURE_BUNDLE_TARGET_IDS
    )
    assert workspace_apply_payload["counts"]["decision_count"] == 4
    assert workspace_apply_payload["counts"]["accepted"] == 1
    assert workspace_apply_payload["counts"]["rejected"] == 2
    assert workspace_apply_payload["decisions"][-1]["decision"] == "rejected"
    assert workspace_apply_payload["decisions"][-1]["candidate_ref"] == (
        UNDECIDED_DEPARTURE_BUNDLE_CANDIDATE_REF
    )
    assert workspace_apply_payload["decisions"][-1]["target_ids"] == (
        UNDECIDED_DEPARTURE_BUNDLE_TARGET_IDS
    )
    assert REPO_REVIEW_DECISION_LOG.read_bytes() == original_review_log
    assert REPO_REVIEW_DECISION_APPLY_PLAN.read_bytes() == original_apply_plan


def test_pretrip_workspace_corrected_review_flow_regenerates_workspace_apply_plan_only(
    tmp_path,
):
    original_review_log = REPO_REVIEW_DECISION_LOG.read_bytes()
    original_apply_plan = REPO_REVIEW_DECISION_APPLY_PLAN.read_bytes()
    workspace_root = tmp_path / "pretrip_workspace"
    workspace_project_root = workspace_root / PROJECT_ID
    workspace_review_log = (
        workspace_project_root / "reviews" / "review_decision_log.json"
    )
    workspace_apply_plan = (
        workspace_project_root / "outputs" / "review_decision_apply_plan.json"
    )
    client = TestClient(create_admin_app(pretrip_workspace_root=workspace_root))

    workspace_response = client.post(f"/admin/pretrip/projects/{PROJECT_ID}/workspace")
    review_response = client.post(
        f"/admin/pretrip/projects/{PROJECT_ID}/review-decisions",
        json=_corrected_review_payload(
            candidate_ref=UNDECIDED_DEPARTURE_BUNDLE_CANDIDATE_REF,
            summary="Corrected frozen departure bundle before local planning use.",
            correction_summary="Keep bundle pending until admin confirms final departure readiness.",
            persist_to_workspace=True,
        ),
    )
    apply_plan_response = client.post(
        f"/admin/pretrip/projects/{PROJECT_ID}/review-decision-apply-plan"
    )

    assert workspace_response.status_code == 200
    assert review_response.status_code == 200
    assert apply_plan_response.status_code == 200

    review_payload = review_response.json()
    apply_plan_payload = apply_plan_response.json()
    assert review_payload["artifact_kind"] == "pretrip_review_decision"
    assert review_payload["preview"] is False
    assert review_payload["persisted"] is True
    assert review_payload["counts"]["action_count"] == 4
    assert review_payload["counts"]["accepted_count"] == 1
    assert review_payload["counts"]["corrected_count"] == 2
    assert review_payload["counts"]["rejected_count"] == 1
    assert review_payload["record"]["decision"] == "corrected"
    assert review_payload["record"]["candidate_ref"] == (
        UNDECIDED_DEPARTURE_BUNDLE_CANDIDATE_REF
    )
    assert review_payload["record"]["target_ids"] == (
        UNDECIDED_DEPARTURE_BUNDLE_TARGET_IDS
    )
    assert review_payload["record"]["correction"] == {
        "summary": "Keep bundle pending until admin confirms final departure readiness.",
        "field_updates": {},
        "replacement_ref_ids": [],
    }

    assert apply_plan_payload["artifact_kind"] == "pretrip_review_decision_apply_plan"
    assert apply_plan_payload["persisted"] is True
    assert apply_plan_payload["counts"]["decision_count"] == 4
    assert apply_plan_payload["counts"]["accepted"] == 1
    assert apply_plan_payload["counts"]["corrected"] == 2
    assert apply_plan_payload["counts"]["rejected"] == 1

    for payload in (review_payload, apply_plan_payload):
        assert payload["boundary"]["package_mutation_allowed"] is False
        assert payload["boundary"]["runtime_mutation_allowed"] is False
        assert payload["boundary"]["phase1_runtime_mutation_allowed"] is False
        assert payload["boundary"]["phase2_writeback_allowed"] is False
        assert payload["boundary"]["fixture_file_mutation_allowed"] is False
        assert payload["mutation"]["package_mutated"] is False
        assert payload["mutation"]["runtime_mutated"] is False
        assert payload["mutation"]["phase1_runtime_mutated"] is False
        assert payload["mutation"]["phase2_writeback_performed"] is False
        assert payload["mutation"]["fixture_files_mutated"] is False
        assert payload["mutation"]["workspace_files_mutated"] is True

    workspace_review_payload = json.loads(
        workspace_review_log.read_text(encoding="utf-8")
    )
    workspace_apply_payload = json.loads(
        workspace_apply_plan.read_text(encoding="utf-8")
    )
    assert workspace_review_payload["counts"]["action_count"] == 4
    assert workspace_review_payload["counts"]["accepted_count"] == 1
    assert workspace_review_payload["counts"]["corrected_count"] == 2
    assert workspace_review_payload["counts"]["rejected_count"] == 1
    assert workspace_review_payload["decisions"][-1]["decision"] == "corrected"
    assert workspace_review_payload["decisions"][-1]["candidate_ref"] == (
        UNDECIDED_DEPARTURE_BUNDLE_CANDIDATE_REF
    )
    assert workspace_review_payload["decisions"][-1]["target_ids"] == (
        UNDECIDED_DEPARTURE_BUNDLE_TARGET_IDS
    )
    assert workspace_review_payload["decisions"][-1]["correction"] == {
        "summary": "Keep bundle pending until admin confirms final departure readiness.",
        "field_updates": {},
        "replacement_ref_ids": [],
    }
    assert workspace_apply_payload["counts"]["decision_count"] == 4
    assert workspace_apply_payload["counts"]["accepted"] == 1
    assert workspace_apply_payload["counts"]["corrected"] == 2
    assert workspace_apply_payload["counts"]["rejected"] == 1
    assert workspace_apply_payload["decisions"][-1]["decision"] == "corrected"
    assert workspace_apply_payload["decisions"][-1]["candidate_ref"] == (
        UNDECIDED_DEPARTURE_BUNDLE_CANDIDATE_REF
    )
    assert workspace_apply_payload["decisions"][-1]["target_ids"] == (
        UNDECIDED_DEPARTURE_BUNDLE_TARGET_IDS
    )
    assert REPO_REVIEW_DECISION_LOG.read_bytes() == original_review_log
    assert REPO_REVIEW_DECISION_APPLY_PLAN.read_bytes() == original_apply_plan


def test_pretrip_review_decision_apply_plan_api_rejects_missing_workspace_project(tmp_path):
    workspace_root = tmp_path / "pretrip_workspace"
    workspace_root.mkdir()
    client = TestClient(create_admin_app(pretrip_workspace_root=workspace_root))

    response = client.post(
        f"/admin/pretrip/projects/{PROJECT_ID}/review-decision-apply-plan"
    )

    assert response.status_code == 409
    assert "workspace project.json" in response.json()["detail"]


def test_pretrip_review_decision_apply_plan_api_rejects_missing_workspace_apply_input(
    tmp_path,
):
    workspace_root = _copy_pretrip_workspace(tmp_path)
    (workspace_root / PROJECT_ID / "reviews" / "review_decision_log.json").unlink()
    client = TestClient(create_admin_app(pretrip_workspace_root=workspace_root))

    response = client.post(
        f"/admin/pretrip/projects/{PROJECT_ID}/review-decision-apply-plan"
    )

    assert response.status_code == 409
    assert "missing required review_decision_log_ref" in response.json()["detail"]


def test_pretrip_departure_reviewed_candidates_api_rejects_without_workspace():
    original_fixture_bytes = _repo_fixture_bytes()
    client = TestClient(create_admin_app())

    response = client.post(
        f"/admin/pretrip/projects/{PROJECT_ID}/departure-reviewed-candidates"
    )

    assert response.status_code == 409
    assert "pretrip_workspace_root" in response.json()["detail"]
    assert _repo_fixture_bytes() == original_fixture_bytes


def test_pretrip_departure_reviewed_candidates_api_writes_workspace_only(tmp_path):
    original_fixture_bytes = _repo_fixture_bytes()
    workspace_root = tmp_path / "pretrip_workspace"
    workspace_project_root = workspace_root / PROJECT_ID
    workspace_output = (
        workspace_project_root / "outputs" / "departure_reviewed_candidates.json"
    )
    client = TestClient(create_admin_app(pretrip_workspace_root=workspace_root))

    workspace_response = client.post(f"/admin/pretrip/projects/{PROJECT_ID}/workspace")
    project_response = client.get(f"/admin/pretrip/projects/{PROJECT_ID}")
    gis_item = next(
        item
        for item in project_response.json()["review_queue"]["items"]
        if item["category"] == "gis_perception_cp"
    )
    review_response = client.post(
        f"/admin/pretrip/projects/{PROJECT_ID}/review-decisions",
        json=_accepted_review_payload(
            candidate_ref=gis_item["candidate_ref"],
            summary="Accepted GIS CP as departure addendum candidate evidence.",
            persist_to_workspace=True,
        ),
    )
    apply_plan_response = client.post(
        f"/admin/pretrip/projects/{PROJECT_ID}/review-decision-apply-plan"
    )
    response = client.post(
        f"/admin/pretrip/projects/{PROJECT_ID}/departure-reviewed-candidates"
    )
    project_after_response = client.get(f"/admin/pretrip/projects/{PROJECT_ID}")

    assert workspace_response.status_code == 200
    assert project_response.status_code == 200
    assert review_response.status_code == 200
    assert apply_plan_response.status_code == 200
    assert response.status_code == 200
    assert project_after_response.status_code == 200
    payload = response.json()
    assert payload["artifact_kind"] == "pretrip_departure_reviewed_candidates"
    assert payload["persisted"] is True
    assert payload["counts"] == {
        "source_decision_count": 4,
        "promoted_candidate_count": 3,
        "accepted_count": 2,
        "corrected_count": 1,
        "rejected_audit_count": 1,
        "runtime_truth_count": 0,
    }
    assert payload["boundary"]["source_mutation_allowed"] is False
    assert payload["boundary"]["package_mutation_allowed"] is False
    assert payload["boundary"]["mission_graph_mutation_allowed"] is False
    assert payload["boundary"]["final_mission_graph_mutation_allowed"] is False
    assert payload["boundary"]["runtime_mutation_allowed"] is False
    assert payload["boundary"]["phase1_runtime_mutation_allowed"] is False
    assert payload["boundary"]["phase2_writeback_allowed"] is False
    assert payload["boundary"]["external_api_calls_made"] is False
    assert payload["boundary"]["fixture_file_mutation_allowed"] is False
    assert payload["boundary"]["workspace_file_mutation_allowed"] is True
    assert payload["boundary"]["compiles_mission_graph"] is False
    assert payload["boundary"]["raw_payloads_embedded"] is False
    assert payload["boundary"]["not_departure_approval"] is True
    assert payload["boundary"]["workspace_project_root"] == str(workspace_project_root)
    assert payload["boundary"]["workspace_departure_reviewed_candidates_path"] == str(
        workspace_output
    )
    assert payload["mutation"]["source_mutated"] is False
    assert payload["mutation"]["package_mutated"] is False
    assert payload["mutation"]["mission_graph_mutated"] is False
    assert payload["mutation"]["final_mission_graph_mutated"] is False
    assert payload["mutation"]["runtime_mutated"] is False
    assert payload["mutation"]["phase1_runtime_mutated"] is False
    assert payload["mutation"]["phase2_writeback_performed"] is False
    assert payload["mutation"]["fixture_files_mutated"] is False
    assert payload["mutation"]["workspace_files_mutated"] is True
    assert payload["mutation"]["workspace_departure_reviewed_candidates_mutated"] is True

    output_payload = json.loads(workspace_output.read_text(encoding="utf-8"))
    gis_candidate = next(
        candidate
        for candidate in output_payload["candidates"]
        if candidate["candidate_ref"] == gis_item["candidate_ref"]
    )
    assert output_payload["counts"]["promoted_candidate_count"] == 3
    assert output_payload["boundary"]["not_departure_approval"] is True
    assert output_payload["boundary"]["runtime_mutation_allowed"] is False
    assert gis_candidate["promotion_scope"] == "departure_annotation_candidate"
    assert gis_candidate["runtime_checkin_candidate"] is True
    assert gis_candidate["candidate_only"] is True
    assert gis_candidate["runtime_safety_truth"] is False
    assert gis_candidate["human_review_required_before_runtime_use"] is True

    project_after = project_after_response.json()
    view_summary = project_after["departure_reviewed_candidates"]
    review_section_ids = [
        section["id"]
        for section in project_after["tabs"]["review_workspace"]["sections"]
    ]
    assert view_summary["status"] == "package_addendum_candidate"
    assert view_summary["counts"]["promoted_candidate_count"] == 3
    assert view_summary["boundary"]["runtime_mutation_allowed"] is False
    assert "departure_reviewed_candidates" in review_section_ids
    assert _repo_fixture_bytes() == original_fixture_bytes


def test_pretrip_departure_reviewed_candidates_api_rejects_missing_apply_plan(tmp_path):
    workspace_root = _copy_pretrip_workspace(tmp_path)
    (workspace_root / PROJECT_ID / "outputs" / "review_decision_apply_plan.json").unlink()
    client = TestClient(create_admin_app(pretrip_workspace_root=workspace_root))

    response = client.post(
        f"/admin/pretrip/projects/{PROJECT_ID}/departure-reviewed-candidates"
    )

    assert response.status_code == 409
    assert "missing required review_decision_apply_plan_ref" in response.json()["detail"]


def test_pretrip_expert_contribution_apply_plan_api_rejects_without_workspace():
    original_fixture_bytes = _repo_fixture_bytes()
    client = TestClient(create_admin_app())

    response = client.post(
        f"/admin/pretrip/projects/{PROJECT_ID}/expert-contribution-apply-plan"
    )

    assert response.status_code == 409
    assert "pretrip_workspace_root" in response.json()["detail"]
    assert _repo_fixture_bytes() == original_fixture_bytes


def test_pretrip_expert_contribution_apply_plan_api_writes_workspace_only(tmp_path):
    original_fixture_bytes = _repo_fixture_bytes()
    workspace_root = _copy_pretrip_workspace(tmp_path)
    workspace_apply_plan = (
        workspace_root / PROJECT_ID / "outputs" / "expert_contribution_apply_plan.json"
    )
    client = TestClient(create_admin_app(pretrip_workspace_root=workspace_root))

    response = client.post(
        f"/admin/pretrip/projects/{PROJECT_ID}/expert-contribution-apply-plan"
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["artifact_kind"] == "pretrip_expert_contribution_apply_plan"
    assert payload["persisted"] is True
    assert payload["counts"]["planned_operation_count"] == 3
    assert payload["counts"]["candidate_set_operation_count"] == 2
    assert payload["counts"]["external_import_operation_count"] == 1
    assert payload["counts"]["source_artifact_mutation_count"] == 0
    assert payload["counts"]["package_mutation_count"] == 0
    assert payload["counts"]["runtime_mutation_count"] == 0
    assert payload["counts"]["phase2_brain_writeback_count"] == 0
    assert payload["boundary"]["candidate_artifact_mutation_allowed"] is False
    assert payload["boundary"]["external_import_queue_mutation_allowed"] is False
    assert payload["boundary"]["package_mutation_allowed"] is False
    assert payload["boundary"]["mission_graph_mutation_allowed"] is False
    assert payload["boundary"]["runtime_mutation_allowed"] is False
    assert payload["boundary"]["phase1_runtime_mutation_allowed"] is False
    assert payload["boundary"]["phase2_writeback_allowed"] is False
    assert payload["boundary"]["fixture_file_mutation_allowed"] is False
    assert payload["boundary"]["workspace_file_mutation_allowed"] is True
    assert payload["boundary"]["workspace_expert_contribution_apply_plan_path"] == str(
        workspace_apply_plan
    )
    assert payload["mutation"]["candidate_artifacts_mutated"] is False
    assert payload["mutation"]["external_import_queue_mutated"] is False
    assert payload["mutation"]["workspace_expert_contribution_apply_plan_mutated"] is True
    assert workspace_apply_plan.is_file()
    assert not REPO_EXPERT_CONTRIBUTION_APPLY_PLAN.exists()
    assert _repo_fixture_bytes() == original_fixture_bytes


def test_pretrip_expert_contribution_workspace_apply_result_api_mutates_workspace_only(
    tmp_path,
):
    original_fixture_bytes = _repo_fixture_bytes()
    workspace_root = _copy_pretrip_workspace(tmp_path)
    workspace_project_root = workspace_root / PROJECT_ID
    workspace_apply_result = (
        workspace_project_root
        / "outputs"
        / "expert_contribution_workspace_apply_result.json"
    )
    workspace_checkpoints = workspace_project_root / "candidates" / "checkpoints.json"
    workspace_retreat_routes = (
        workspace_project_root / "candidates" / "retreat_routes.json"
    )
    workspace_import_queue = (
        workspace_project_root / "outputs" / "external_import_queue.json"
    )
    before_checkpoints = json.loads(workspace_checkpoints.read_text(encoding="utf-8"))
    before_import_queue = json.loads(workspace_import_queue.read_text(encoding="utf-8"))
    client = TestClient(create_admin_app(pretrip_workspace_root=workspace_root))

    response = client.post(
        f"/admin/pretrip/projects/{PROJECT_ID}/expert-contribution-workspace-apply-result"
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["artifact_kind"] == (
        "pretrip_expert_contribution_workspace_apply_result"
    )
    assert payload["persisted"] is True
    assert payload["counts"]["planned_operation_count"] == 3
    assert payload["counts"]["applied_operation_count"] == 3
    assert payload["counts"]["checkpoint_candidate_append_count"] == 1
    assert payload["counts"]["retreat_route_update_count"] == 1
    assert payload["counts"]["external_import_request_append_count"] == 1
    assert payload["counts"]["package_mutation_count"] == 0
    assert payload["counts"]["runtime_mutation_count"] == 0
    assert payload["counts"]["phase2_brain_writeback_count"] == 0
    assert payload["boundary"]["workspace_candidate_artifact_mutation_allowed"] is True
    assert payload["boundary"]["workspace_external_import_queue_mutation_allowed"] is True
    assert payload["boundary"]["package_mutation_allowed"] is False
    assert payload["boundary"]["mission_graph_mutation_allowed"] is False
    assert payload["boundary"]["runtime_mutation_allowed"] is False
    assert payload["boundary"]["phase1_runtime_mutation_allowed"] is False
    assert payload["boundary"]["phase2_writeback_allowed"] is False
    assert payload["boundary"]["fixture_file_mutation_allowed"] is False
    assert payload["boundary"]["workspace_expert_contribution_apply_result_path"] == str(
        workspace_apply_result
    )
    assert payload["mutation"]["workspace_candidate_artifacts_mutated"] is True
    assert payload["mutation"]["workspace_external_import_queue_mutated"] is True
    assert payload["mutation"]["fixture_files_mutated"] is False
    assert workspace_apply_result.is_file()

    after_checkpoints = json.loads(workspace_checkpoints.read_text(encoding="utf-8"))
    after_retreat_routes = json.loads(workspace_retreat_routes.read_text(encoding="utf-8"))
    after_import_queue = json.loads(workspace_import_queue.read_text(encoding="utf-8"))
    assert len(after_checkpoints) == len(before_checkpoints) + 1
    assert after_checkpoints[-1]["review_state"] == "needs_human_review"
    assert after_import_queue["counts"]["request_count"] == (
        before_import_queue["counts"]["request_count"] + 1
    )
    assert after_import_queue["requests"][-1]["network_call_count"] == 0
    assert after_import_queue["requests"][-1]["raw_payload_embedded"] is False
    assert any(
        route.get("review_state") == "needs_human_review"
        and "Expert update" in route.get("notes", "")
        for route in after_retreat_routes
    )
    assert not REPO_EXPERT_CONTRIBUTION_WORKSPACE_APPLY_RESULT.exists()
    assert _repo_fixture_bytes() == original_fixture_bytes


def test_pretrip_project_api_overlays_expert_contribution_workspace_apply_result(
    tmp_path,
):
    workspace_root = _copy_pretrip_workspace(tmp_path)
    client = TestClient(create_admin_app(pretrip_workspace_root=workspace_root))

    apply_response = client.post(
        f"/admin/pretrip/projects/{PROJECT_ID}/expert-contribution-workspace-apply-result"
    )
    view_response = client.get(f"/admin/pretrip/projects/{PROJECT_ID}")

    assert apply_response.status_code == 200
    assert view_response.status_code == 200
    view = view_response.json()
    assert view["expert_contribution_apply_plan"]["counts"][
        "planned_operation_count"
    ] == 3
    result = view["expert_contribution_workspace_apply_result"]
    assert result["counts"]["applied_operation_count"] == 3
    assert result["boundary"]["workspace_candidate_artifact_mutation_allowed"] is True
    assert result["boundary"]["runtime_mutation_allowed"] is False
    sections = {
        section["id"]: section
        for section in view["tabs"]["review_workspace"]["sections"]
    }
    assert sections["expert_contribution_apply_plan"]["counts"][
        "planned_operation_count"
    ] == 3
    assert sections["expert_contribution_workspace_apply_result"]["counts"][
        "applied_operation_count"
    ] == 3


def test_pretrip_import_gpx_preview_api_is_no_write(tmp_path):
    workspace_root = tmp_path / "workspaces"
    golden = tmp_path / "gpx" / "golden.gpx"
    reference = tmp_path / "gpx" / "references" / "expert.gpx"
    _write_small_gpx(
        golden,
        name="Golden reference route",
        points=[
            (24.0910, 121.1810, 2200.0),
            (24.0925, 121.1835, 2260.0),
            (24.0940, 121.1860, 2310.0),
        ],
    )
    _write_small_gpx(
        reference,
        name="Expert reference route",
        points=[
            (24.0908, 121.1808, 2190.0),
            (24.0924, 121.1832, 2255.0),
            (24.0942, 121.1862, 2305.0),
        ],
    )
    client = TestClient(create_admin_app(pretrip_workspace_root=workspace_root))

    response = client.post(
        "/admin/pretrip/projects/imported/import-gpx-preview",
        json={
            "golden_route_gpx": str(golden),
            "reference_dir": str(reference.parent),
            "checkpoint_spacing_m": 25,
            "max_reference_display_points": 10,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["artifact_kind"] == "pretrip_import_gpx_preview"
    assert payload["persisted"] is False
    assert payload["counts"]["golden_route_count"] == 1
    assert payload["counts"]["reference_track_count"] == 1
    assert payload["inputs"]["golden_route_gpx"]["role"] == "golden_route_reference"
    assert payload["boundary"]["admin_api_write_performed"] is False
    assert payload["boundary"]["network_calls_allowed"] is False
    assert payload["boundary"]["phase1_runtime_mutation_allowed"] is False
    assert payload["boundary"]["compiles_mission_graph"] is False
    assert payload["planning_semantics"]["golden_route"]["actual_user_track"] is False
    assert not (workspace_root / "imported").exists()


def test_pretrip_import_gpx_run_api_requires_confirmation_and_writes_workspace(
    tmp_path,
):
    workspace_root = tmp_path / "workspaces"
    golden = tmp_path / "gpx" / "golden.gpx"
    reference = tmp_path / "gpx" / "references" / "expert.gpx"
    _write_small_gpx(
        golden,
        name="Golden reference route",
        points=[
            (24.0910, 121.1810, 2200.0),
            (24.0925, 121.1835, 2260.0),
            (24.0940, 121.1860, 2310.0),
        ],
    )
    _write_small_gpx(
        reference,
        name="Expert reference route",
        points=[
            (24.0908, 121.1808, 2190.0),
            (24.0924, 121.1832, 2255.0),
            (24.0942, 121.1862, 2305.0),
        ],
    )
    client = TestClient(create_admin_app(pretrip_workspace_root=workspace_root))
    payload = {
        "golden_route_gpx": str(golden),
        "reference_dir": str(reference.parent),
        "template_project_root": str(FIXTURE_PROJECT_ROOT),
        "checkpoint_spacing_m": 25,
        "max_reference_display_points": 10,
        "overwrite": False,
    }

    rejected = client.post(
        "/admin/pretrip/projects/imported/import-gpx",
        json=payload,
    )
    response = client.post(
        "/admin/pretrip/projects/imported/import-gpx",
        json={**payload, "confirm_import": True},
    )
    view_response = client.get("/admin/pretrip/projects/imported")

    assert rejected.status_code == 400
    assert response.status_code == 200
    result = response.json()
    assert result["artifact_kind"] == "pretrip_import_gpx_result"
    assert result["persisted"] is True
    assert result["manifest"]["counts"]["golden_route_count"] == 1
    assert result["manifest"]["counts"]["reference_track_count"] == 1
    assert result["manifest"]["boundary"]["actual_user_track_available"] is False
    assert result["boundary"]["admin_api_write_performed"] is True
    assert result["boundary"]["phase1_runtime_mutation_allowed"] is False
    assert result["boundary"]["compiles_mission_graph"] is False
    project_root = workspace_root / "imported"
    assert (project_root / "project.json").exists()
    assert (project_root / "outputs" / "import_manifest.json").exists()
    assert (project_root / "outputs" / "admin_projection.json").exists()
    assert (project_root / "outputs" / "debug_projection_events.jsonl").exists()
    assert view_response.status_code == 200
    view = view_response.json()
    assert view["project_id"] == "imported"
    assert view["reference_tracks"]["reference_track_count"] == 1


def test_pretrip_review_decision_api_returns_corrected_preview_record():
    client = TestClient(create_admin_app())

    response = client.post(
        f"/admin/pretrip/projects/{PROJECT_ID}/review-decisions",
        json={
            "candidate_ref": "policy_candidate.chilai_nanhua_day1.seg.001",
            "decision": "corrected",
            "reviewer_alias": "trip_leader",
            "summary": "Corrected segment policy fields without writing the package.",
            "target_ids": ["seg.001"],
            "correction": {
                "summary": "Keep water status reviewer-confirmed.",
                "field_updates": {"water_available": "reviewer_confirmed_unknown"},
            },
        },
    )

    assert response.status_code == 200
    payload = response.json()
    record = payload["record"]
    assert record["decision"] == "corrected"
    assert record["candidate_ref"] == "policy_candidate.chilai_nanhua_day1.seg.001"
    assert record["target_ids"] == ["seg.001"]
    assert record["correction"] == {
        "summary": "Keep water status reviewer-confirmed.",
        "field_updates": {"water_available": "reviewer_confirmed_unknown"},
        "replacement_ref_ids": [],
    }
    assert record["package_mutation_allowed"] is False
    assert record["runtime_mutation_allowed"] is False
    assert record["phase1_runtime_mutation_allowed"] is False
    assert record["phase2_writeback_allowed"] is False
    assert payload["boundary"]["append_only"] is True
    assert payload["boundary"]["compiles_mission_graph"] is False


def test_pretrip_review_decision_api_rejects_unknown_project():
    client = TestClient(create_admin_app())

    response = client.post(
        "/admin/pretrip/projects/missing/review-decisions",
        json={
            "candidate_ref": "contour.g11.seg_001_003",
            "decision": "accepted",
            "summary": "Accepted.",
        },
    )

    assert response.status_code == 404


def test_pretrip_review_decision_api_rejects_bad_input():
    client = TestClient(create_admin_app())

    bad_decision = client.post(
        f"/admin/pretrip/projects/{PROJECT_ID}/review-decisions",
        json={
            "candidate_ref": "contour.g11.seg_001_003",
            "decision": "approved",
            "summary": "Invalid decision.",
        },
    )
    missing_correction = client.post(
        f"/admin/pretrip/projects/{PROJECT_ID}/review-decisions",
        json={
            "candidate_ref": "policy_candidate.chilai_nanhua_day1.seg.001",
            "decision": "corrected",
            "summary": "Corrected without correction fields.",
        },
    )
    unknown_candidate = client.post(
        f"/admin/pretrip/projects/{PROJECT_ID}/review-decisions",
        json={
            "candidate_ref": "candidate.missing",
            "decision": "accepted",
            "summary": "Unknown candidate.",
        },
    )

    assert bad_decision.status_code == 422
    assert missing_correction.status_code == 422
    assert unknown_candidate.status_code == 422
