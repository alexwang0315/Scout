import json
import shutil
from pathlib import Path

from fastapi.testclient import TestClient

from admin_api import create_admin_app
from pretrip_admin_view import build_pretrip_admin_view
from pretrip_energy_projection import (
    DEFAULT_PRETRIP_ENERGY_PROJECTION_REF,
    PreTripEnergyReserveProjection,
    write_pretrip_energy_reserve_projection,
)
from scout_energy_models import load_wearable_activity_summaries
from scout_energy_reserve import write_energy_reserve_artifacts


ROOT = Path(__file__).resolve().parents[1]
WEARABLE_FIXTURE_ROOT = ROOT / "tests" / "fixtures" / "wearables"
WEARABLE_FIXTURES = [
    WEARABLE_FIXTURE_ROOT / "apple_health_clean_activity.json",
    WEARABLE_FIXTURE_ROOT / "apple_health_missing_hr_interval.json",
    WEARABLE_FIXTURE_ROOT / "garmin_body_battery_provider_values.json",
]
PRETRIP_FIXTURE_ROOT = ROOT / "tests" / "fixtures" / "pretrip" / "projects" / "chilai_nanhua_day1"
POST_ANALYSIS_OUTPUTS = (
    ROOT
    / "tests"
    / "fixtures"
    / "post_analysis"
    / "chilai_nanhua_day1_post_analysis"
    / "outputs"
)


def test_writes_energy_baseline_explanation_and_companion_artifacts(tmp_path):
    activities = load_wearable_activity_summaries(WEARABLE_FIXTURES, root=ROOT)

    result = write_energy_reserve_artifacts(
        activities,
        output_dir=tmp_path,
    )

    baseline = result["baseline"]
    explanation = result["explanation"]
    capsule = result["companion_capsule"]
    assert Path(result["baseline_path"]).exists()
    assert Path(result["explanation_path"]).exists()
    assert Path(result["companion_capsule_path"]).exists()
    assert baseline["source_provider"] == "mixed_wearable_activity_summaries"
    assert baseline["privacy"]["raw_samples_embedded"] is False
    assert explanation["reserve_band"] == baseline["reserve_trend"]["current_band"]
    assert "medical diagnosis" in explanation["forbidden_interpretations"]
    assert capsule["raw_health_payload_shared"] is False
    assert capsule["boundary"]["phase1_runtime_safety_truth"] is False


def test_pretrip_energy_projection_adjusts_eta_and_marks_depletion_checkpoint(tmp_path):
    workspace_project_root = tmp_path / "chilai_nanhua_day1"
    shutil.copytree(PRETRIP_FIXTURE_ROOT, workspace_project_root)
    activities = load_wearable_activity_summaries(WEARABLE_FIXTURES, root=ROOT)
    energy = write_energy_reserve_artifacts(
        activities,
        output_dir=workspace_project_root / "outputs",
    )

    projection = write_pretrip_energy_reserve_projection(
        eta_plan_path=workspace_project_root / "outputs" / "planned_eta.json",
        energy_baseline_path=Path(energy["baseline_path"]),
        output_path=workspace_project_root / DEFAULT_PRETRIP_ENERGY_PROJECTION_REF,
        project_root=workspace_project_root,
    )
    payload = projection.model_dump(mode="json")

    assert payload["artifact_kind"] == "pretrip_energy_reserve_projection"
    assert payload["projected_target_eta"] > "2026-05-03T15:25:35+08:00"
    assert payload["possible_depletion_checkpoint_name"] == "雲海保線所"
    assert any(
        checkpoint["possible_depletion_checkpoint"]
        for checkpoint in payload["checkpoints"]
    )
    assert payload["boundary"]["medical_diagnosis"] is False
    assert payload["boundary"]["phase1_runtime_safety_truth"] is False
    assert payload["privacy"]["raw_track_shared"] is False
    PreTripEnergyReserveProjection.model_validate(payload)

    view = build_pretrip_admin_view("chilai_nanhua_day1", root=ROOT, project_root=workspace_project_root)
    energy_view = view["eta"]["energy_reserve_projection"]
    assert energy_view["projected_target_eta"] == payload["projected_target_eta"]
    assert energy_view["possible_depletion_checkpoint_name"] == "雲海保線所"
    assert energy_view["boundary"]["safety_api_calls_allowed"] is False
    assert view["tabs"]["pre_trip_planning"]["eta"]["energy_reserve_projection"] == energy_view


def test_admin_wearable_inventory_import_delete_and_refresh(tmp_path, monkeypatch):
    monkeypatch.setenv("SCOUT_DATA_ROOT", str(tmp_path / "data"))
    client = TestClient(create_admin_app())

    empty = client.get("/admin/wearables")
    assert empty.status_code == 200
    assert empty.json()["activity_count"] == 0

    imported = client.post(
        "/admin/wearables/import",
        json={"source_path": str(WEARABLE_FIXTURES[0])},
    )
    assert imported.status_code == 200
    assert imported.json()["source_provider"] == "apple_health_export"
    assert imported.json()["boundary"]["medical_diagnosis"] is False
    assert imported.json()["validation"]["valid"] is True

    second = client.post(
        "/admin/wearables/import",
        json={"source_path": str(WEARABLE_FIXTURES[1])},
    )
    assert second.status_code == 200

    inventory = client.get("/admin/wearables").json()
    assert inventory["activity_count"] == 2
    assert all(item["phase1_runtime_safety_truth"] is False for item in inventory["activities"])

    refresh = client.post(
        "/admin/wearables/refresh-energy",
        json={"reference_date": "2026-05-27"},
    )
    assert refresh.status_code == 200
    refreshed = refresh.json()
    assert refreshed["artifact_kind"] == "scout_wearable_energy_refresh_result"
    assert refreshed["source_provider"] == "apple_health_export"
    assert refreshed["privacy"]["raw_samples_embedded"] is False
    assert refreshed["boundary"]["safety_api_calls_allowed"] is False
    assert Path(refreshed["baseline_path"]).exists()

    activity_id = imported.json()["activity_id"]
    deleted = client.post("/admin/wearables/delete", json={"activity_id": activity_id})
    assert deleted.status_code == 200
    assert deleted.json()["mutation"]["inventory_file_deleted"] is True
    assert client.get("/admin/wearables").json()["activity_count"] == 1
    assert "/safety/" not in json.dumps(refreshed)


def test_admin_validates_wearable_summary_before_import(tmp_path, monkeypatch):
    monkeypatch.setenv("SCOUT_DATA_ROOT", str(tmp_path / "data"))
    client = TestClient(create_admin_app())

    validation = client.post(
        "/admin/wearables/validate",
        json={"source_path": str(WEARABLE_FIXTURES[0])},
    )
    assert validation.status_code == 200
    payload = validation.json()
    assert payload["valid"] is True
    assert payload["privacy"]["raw_health_payload_shared"] is False
    assert payload["boundary"]["phase1_runtime_safety_truth"] is False

    bad_payload = json.loads(WEARABLE_FIXTURES[0].read_text(encoding="utf-8"))
    bad_payload["raw_health_payload"] = {"forbidden": True}
    bad_path = tmp_path / "bad_wearable_summary.json"
    bad_path.write_text(json.dumps(bad_payload), encoding="utf-8")
    bad = client.post(
        "/admin/wearables/validate",
        json={"source_path": str(bad_path)},
    )
    assert bad.status_code == 200
    assert bad.json()["valid"] is False
    imported = client.post(
        "/admin/wearables/import",
        json={"source_path": str(bad_path)},
    )
    assert imported.status_code == 422


def test_admin_refreshes_pretrip_energy_projection_from_wearable_inventory(tmp_path, monkeypatch):
    monkeypatch.setenv("SCOUT_DATA_ROOT", str(tmp_path / "data"))
    workspace_root = tmp_path / "workspaces"
    workspace_project_root = workspace_root / "chilai_nanhua_day1"
    shutil.copytree(PRETRIP_FIXTURE_ROOT, workspace_project_root)
    client = TestClient(create_admin_app(pretrip_workspace_root=workspace_root))

    for fixture in WEARABLE_FIXTURES:
        response = client.post(
            "/admin/wearables/import",
            json={"source_path": str(fixture)},
        )
        assert response.status_code == 200
    refresh = client.post(
        "/admin/pretrip/projects/chilai_nanhua_day1/refresh-energy-projection",
        json={"reference_date": "2026-05-27"},
    )

    assert refresh.status_code == 200
    payload = refresh.json()
    assert payload["artifact_kind"] == "pretrip_energy_projection_refresh_result"
    assert payload["projection"]["possible_depletion_checkpoint_name"] == "雲海保線所"
    assert payload["boundary"]["phase1_runtime_safety_truth"] is False
    assert payload["mutation"]["workspace_energy_projection_written"] is True
    assert Path(payload["paths"]["energy_projection"]).exists()

    view = client.get("/admin/pretrip/projects/chilai_nanhua_day1")
    assert view.status_code == 200
    energy_view = view.json()["eta"]["energy_reserve_projection"]
    assert energy_view["possible_depletion_checkpoint_name"] == "雲海保線所"
    assert energy_view["boundary"]["safety_api_calls_allowed"] is False
    review_queue = view.json()["review_queue"]
    assert review_queue["counts"]["energy_reserve_count"] == 1
    energy_items = [
        item for item in review_queue["items"] if item["category"] == "energy_reserve"
    ]
    assert energy_items[0]["severity"] == "warning"
    assert energy_items[0]["evidence_summary"]["runtime_safety_truth"] is False


def test_admin_refreshes_companion_match_review_from_wearable_inventory(tmp_path, monkeypatch):
    monkeypatch.setenv("SCOUT_DATA_ROOT", str(tmp_path / "data"))
    workspace_root = tmp_path / "workspaces"
    workspace_project_root = workspace_root / "chilai_nanhua_day1"
    shutil.copytree(PRETRIP_FIXTURE_ROOT, workspace_project_root)
    shutil.copy2(
        POST_ANALYSIS_OUTPUTS / "capability_timeline.json",
        workspace_project_root / "outputs" / "capability_timeline.json",
    )
    client = TestClient(create_admin_app(pretrip_workspace_root=workspace_root))

    for fixture in WEARABLE_FIXTURES:
        response = client.post(
            "/admin/wearables/import",
            json={"source_path": str(fixture)},
        )
        assert response.status_code == 200
    refresh = client.post(
        "/admin/pretrip/projects/chilai_nanhua_day1/refresh-companion-match",
        json={},
    )

    assert refresh.status_code == 200
    payload = refresh.json()
    assert payload["artifact_kind"] == "pretrip_companion_match_refresh_result"
    assert payload["persisted"] is True
    assert payload["companion_match_review"]["artifact_kind"] == "scout_companion_match_review"
    assert payload["companion_match_review"]["candidate_count"] == 1
    assert payload["companion_match_review"]["ranked_matches"][0]["candidate_profile_ref"] == (
        "post_analysis_capability_timeline"
    )
    assert payload["boundary"]["medical_diagnosis"] is False
    assert payload["boundary"]["phase1_runtime_safety_truth"] is False
    assert payload["boundary"]["safety_api_calls_allowed"] is False
    assert payload["boundary"]["pretrip_eta_autocalibration_allowed"] is False
    assert payload["boundary"]["mission_graph_compile_allowed"] is False
    assert payload["mutation"]["workspace_companion_match_review_written"] is True
    assert payload["mutation"]["raw_health_payload_shared"] is False
    assert Path(payload["paths"]["companion_match_review"]).exists()

    view = client.get("/admin/pretrip/projects/chilai_nanhua_day1")
    assert view.status_code == 200
    companion = view.json()["companion_match_review"]
    assert companion["counts"]["candidate_count"] == 1
    assert companion["boundary"]["runtime_safety_truth"] is False
    assert companion["summary"]["auto_applies_to_eta"] is False
    assert "/safety/" not in json.dumps(payload)


def test_admin_refreshes_post_analysis_energy_feedback_from_workspace_outputs(tmp_path, monkeypatch):
    monkeypatch.setenv("SCOUT_DATA_ROOT", str(tmp_path / "data"))
    workspace_root = tmp_path / "workspaces"
    workspace_project_root = workspace_root / "chilai_nanhua_day1"
    shutil.copytree(PRETRIP_FIXTURE_ROOT, workspace_project_root)
    shutil.copy2(
        POST_ANALYSIS_OUTPUTS / "capability_timeline.json",
        workspace_project_root / "outputs" / "capability_timeline.json",
    )
    client = TestClient(create_admin_app(pretrip_workspace_root=workspace_root))

    for fixture in WEARABLE_FIXTURES:
        response = client.post(
            "/admin/wearables/import",
            json={"source_path": str(fixture)},
        )
        assert response.status_code == 200
    projection = client.post(
        "/admin/pretrip/projects/chilai_nanhua_day1/refresh-energy-projection",
        json={"reference_date": "2026-05-27"},
    )
    assert projection.status_code == 200

    refresh = client.post(
        "/admin/pretrip/projects/chilai_nanhua_day1/refresh-energy-feedback",
        json={},
    )

    assert refresh.status_code == 200
    payload = refresh.json()
    assert payload["artifact_kind"] == "post_analysis_energy_feedback_refresh_result"
    assert payload["post_analysis_energy_feedback"]["artifact_kind"] == (
        "post_analysis_energy_reserve_feedback"
    )
    assert payload["post_analysis_energy_feedback"]["predicted_depletion_checkpoint_name"] == (
        "雲海保線所"
    )
    assert payload["boundary"]["medical_diagnosis"] is False
    assert payload["boundary"]["phase1_runtime_safety_truth"] is False
    assert payload["boundary"]["safety_api_calls_allowed"] is False
    assert payload["boundary"]["pretrip_eta_autocalibration_allowed"] is False
    assert payload["boundary"]["mission_graph_compile_allowed"] is False
    assert payload["mutation"]["workspace_energy_feedback_written"] is True
    assert payload["mutation"]["raw_track_shared"] is False
    assert Path(payload["paths"]["post_analysis_energy_feedback"]).exists()

    view = client.get("/admin/pretrip/projects/chilai_nanhua_day1")
    assert view.status_code == 200
    feedback = view.json()["post_analysis_energy_feedback"]
    assert feedback["summary"]["predicted_depletion_checkpoint_name"] == "雲海保線所"
    assert feedback["summary"]["auto_applies_to_eta"] is False
    assert feedback["boundary"]["runtime_safety_truth"] is False
    assert "<trkpt" not in json.dumps(feedback)
    assert "/safety/" not in json.dumps(payload)
