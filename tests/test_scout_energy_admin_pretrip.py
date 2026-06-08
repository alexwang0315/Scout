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
    assert payload["projected_target_eta"] > "2013-10-08T18:28:50+08:00"
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


def test_admin_exports_and_deletes_wearable_energy_artifacts_with_consent(tmp_path, monkeypatch):
    monkeypatch.setenv("SCOUT_DATA_ROOT", str(tmp_path / "data"))
    client = TestClient(create_admin_app())

    for fixture in WEARABLE_FIXTURES:
        imported = client.post(
            "/admin/wearables/import",
            json={"source_path": str(fixture)},
        )
        assert imported.status_code == 200
    refresh = client.post(
        "/admin/wearables/refresh-energy",
        json={"reference_date": "2026-05-27"},
    )
    assert refresh.status_code == 200
    baseline_path = Path(refresh.json()["baseline_path"])
    capsule_path = Path(refresh.json()["companion_capsule_path"])
    assert baseline_path.exists()
    assert capsule_path.exists()

    rejected = client.post(
        "/admin/wearables/export-energy",
        json={"explicit_consent": False},
    )
    assert rejected.status_code == 422

    exported = client.post(
        "/admin/wearables/export-energy",
        json={
            "explicit_consent": True,
            "include_reserve_summary": True,
        },
    )
    assert exported.status_code == 200
    export_payload = exported.json()
    export_path = Path(export_payload["export_path"])
    export_bundle = export_payload["export"]
    assert export_path.exists()
    assert export_bundle["artifact_kind"] == "scout_wearable_energy_export_bundle"
    assert export_bundle["consent"]["explicit_local_export"] is True
    assert export_bundle["consent"]["remote_share_allowed"] is False
    assert export_bundle["consent"]["community_pool_upload_allowed"] is False
    assert export_bundle["consent"]["raw_health_payload_shared"] is False
    assert export_bundle["consent"]["raw_track_shared"] is False
    assert export_bundle["consent"]["exact_timestamps_shared"] is False
    assert export_bundle["consent"]["route_family_names_shared"] is False
    assert export_bundle["privacy"]["shareable_by_default"] is False
    assert export_bundle["boundary"]["medical_diagnosis"] is False
    assert export_bundle["boundary"]["phase1_runtime_safety_truth"] is False
    assert "companion_capability_capsule" in export_bundle["artifacts"]
    reserve_summary = export_bundle["artifacts"]["energy_reserve_summary"]
    assert reserve_summary["route_family_profiles_shared"] is False
    reserve_summary_text = json.dumps(reserve_summary)
    assert '"route_family_profiles":' not in reserve_summary_text
    assert "local_day_hike" not in reserve_summary_text

    deleted = client.post(
        "/admin/wearables/delete-energy",
        json={"include_exports": True},
    )
    assert deleted.status_code == 200
    delete_payload = deleted.json()
    assert delete_payload["artifact_kind"] == "scout_wearable_energy_delete_result"
    assert delete_payload["activity_summaries_deleted"] is False
    assert delete_payload["mutation"]["safety_api_called"] is False
    assert not baseline_path.exists()
    assert not capsule_path.exists()
    assert not export_path.exists()
    assert client.get("/admin/wearables").json()["activity_count"] == 3
    assert "/safety/" not in json.dumps(export_payload)


def test_admin_builds_daily_home_energy_overview(tmp_path, monkeypatch):
    monkeypatch.setenv("SCOUT_DATA_ROOT", str(tmp_path / "data"))
    client = TestClient(create_admin_app())

    for fixture in WEARABLE_FIXTURES:
        imported = client.post(
            "/admin/wearables/import",
            json={"source_path": str(fixture)},
        )
        assert imported.status_code == 200

    response = client.post(
        "/admin/wearables/daily-energy",
        json={"reference_date": "2026-05-27"},
    )

    assert response.status_code == 200
    payload = response.json()
    overview = payload["overview"]
    overview_path = Path(payload["overview_path"])
    assert payload["artifact_kind"] == "scout_wearable_daily_energy_overview_result"
    assert overview_path.exists()
    assert overview["artifact_kind"] == "scout_wearable_daily_energy_overview"
    assert overview["surface"] == "daily_home"
    assert overview["current_reserve_band"] == "rest_suggested"
    assert overview["trend_vs_baseline"]["acute_7_day_load"]["activity_count"] == 1
    assert overview["trend_vs_baseline"]["recent_28_day_baseline"]["activity_count"] == 2
    assert overview["trend_vs_baseline"]["stable_90_day_baseline"]["activity_count"] == 3
    assert overview["next_day_soft_cue"]["cue_type"] == "rest_or_easy_day"
    assert overview["next_day_soft_cue"]["medical_language"] is False
    assert overview["next_day_soft_cue"]["phase1_runtime_safety_truth"] is False
    assert overview["display_language_policy"]["medical_language_allowed"] is False
    assert overview["display_language_policy"]["runtime_safety_truth"] is False
    assert overview["boundary"]["medical_diagnosis"] is False
    assert overview["boundary"]["phase1_runtime_safety_truth"] is False
    assert overview["boundary"]["safety_api_calls_allowed"] is False
    assert payload["mutation"]["safety_api_called"] is False
    assert payload["privacy"]["raw_health_payload_shared"] is False
    assert "/safety/" not in json.dumps(payload)


def test_admin_builds_provider_live_preflight_and_request_plan_without_network(tmp_path, monkeypatch):
    monkeypatch.setenv("SCOUT_DATA_ROOT", str(tmp_path / "data"))
    client = TestClient(create_admin_app())

    preflight_response = client.post(
        "/admin/wearables/provider-live-preflight",
        json={
            "provider": "garmin_health_api_live",
            "account_ref": "garmin.account.private",
            "device_ref": "garmin.watch.private",
            "auth_token_ref": "secret-token-value",
            "scopes": ["activity:read", "heart_rate:read", "body_energy:read"],
            "capabilities": [
                "activity_summary_import",
                "heart_rate_samples",
                "provider_body_energy_source_values",
            ],
            "explicit_consent": True,
        },
    )
    assert preflight_response.status_code == 200
    preflight_payload = preflight_response.json()
    preflight_path = Path(preflight_payload["preflight_path"])
    assert preflight_payload["artifact_kind"] == "scout_wearable_provider_live_transport_preflight_result"
    assert preflight_path.exists()
    assert preflight_payload["preflight"]["transport"]["network_request_performed"] is False
    assert preflight_payload["preflight"]["transport"]["real_provider_api_called"] is False
    assert preflight_payload["preflight"]["transport"]["runtime_ingest_performed"] is False

    request_plan_response = client.post(
        "/admin/wearables/provider-live-request-plan",
        json={
            "window_start_date": "2026-05-20",
            "window_end_date": "2026-05-27",
            "capabilities": ["activity_summary_import", "provider_body_energy_source_values"],
        },
    )
    assert request_plan_response.status_code == 200
    request_plan_payload = request_plan_response.json()
    request_plan = request_plan_payload["request_plan"]
    serialized = json.dumps([preflight_payload, request_plan_payload])

    assert request_plan_payload["artifact_kind"] == "scout_wearable_provider_live_transport_request_plan_result"
    assert Path(request_plan_payload["request_plan_path"]).exists()
    assert request_plan["source_provider"] == "garmin_health_api_live"
    assert request_plan["source_path"] == str(preflight_path)
    assert request_plan["transport"]["request_executor_bound"] is False
    assert request_plan["transport"]["network_request_performed"] is False
    assert request_plan["transport"]["real_provider_api_called"] is False
    assert request_plan["transport"]["runtime_ingest_performed"] is False
    assert request_plan["mutation"]["safety_api_called"] is False
    assert request_plan["privacy"]["raw_health_payload_shared"] is False
    assert request_plan["boundary"]["medical_diagnosis"] is False
    assert request_plan["boundary"]["phase1_runtime_safety_truth"] is False
    assert "secret-token-value" not in serialized
    assert "garmin.account.private" not in serialized
    assert "garmin.watch.private" not in serialized
    assert "/safety/" not in serialized

    readiness_response = client.post(
        "/admin/wearables/provider-live-executor-readiness",
        json={
            "request_plan_path": request_plan_payload["request_plan_path"],
        },
    )
    assert readiness_response.status_code == 200
    readiness_payload = readiness_response.json()
    readiness = readiness_payload["executor_readiness"]
    readiness_serialized = json.dumps(readiness_payload)

    assert readiness_payload["artifact_kind"] == "scout_wearable_provider_live_executor_readiness_result"
    assert Path(readiness_payload["executor_readiness_path"]).exists()
    assert readiness["source_provider"] == "garmin_health_api_live"
    assert readiness["ready_for_live_execution"] is False
    assert readiness["execution_blockers"] == [
        "live_provider_executor_not_registered",
        "network_execution_disabled_by_local_contract",
    ]
    assert readiness["prerequisite_review"]["request_plan_valid"] is True
    assert readiness["transport"]["network_request_performed"] is False
    assert readiness["transport"]["real_provider_api_called"] is False
    assert readiness["transport"]["runtime_ingest_performed"] is False

    assert readiness["mutation"]["phase1_runtime_mutated"] is False
    assert readiness["boundary"]["medical_diagnosis"] is False
    assert readiness["boundary"]["phase1_runtime_safety_truth"] is False
    assert "secret-token-value" not in readiness_serialized
    assert "garmin.account.private" not in readiness_serialized
    assert "garmin.watch.private" not in readiness_serialized
    assert "/safety/" not in readiness_serialized

    registration_response = client.post(
        "/admin/wearables/provider-live-register-executor",
        json={
            "preflight_path": preflight_payload["preflight_path"],
            "executor_kind": "garmin_health_api_client",
            "executor_ref": "admin.garmin.executor.private",
            "capabilities": ["activity_summary_import", "provider_body_energy_source_values"],
        },
    )
    assert registration_response.status_code == 200
    registration_payload = registration_response.json()
    registration = registration_payload["executor_registration"]
    registration_serialized = json.dumps(registration_payload)

    assert registration_payload["artifact_kind"] == "scout_wearable_provider_live_executor_registration_result"
    assert Path(registration_payload["executor_registration_path"]).exists()
    assert registration["source_provider"] == "garmin_health_api_live"
    assert registration["executor_registration"]["executor_registered"] is True
    assert registration["executor_registration"]["executor_ref_exposed"] is False
    assert registration["transport"]["network_request_performed"] is False
    assert registration["transport"]["real_provider_api_called"] is False
    assert registration["transport"]["runtime_ingest_performed"] is False
    assert "admin.garmin.executor.private" not in registration_serialized
    assert "secret-token-value" not in registration_serialized
    assert "garmin.account.private" not in registration_serialized
    assert "garmin.watch.private" not in registration_serialized
    assert "/safety/" not in registration_serialized

    registered_readiness_response = client.post(
        "/admin/wearables/provider-live-executor-readiness",
        json={
            "request_plan_path": request_plan_payload["request_plan_path"],
            "executor_registration_path": registration_payload["executor_registration_path"],
        },
    )
    assert registered_readiness_response.status_code == 200
    registered_readiness = registered_readiness_response.json()["executor_readiness"]

    assert registered_readiness["ready_for_live_execution"] is False
    assert registered_readiness["execution_blockers"] == [
        "network_execution_disabled_by_local_contract"
    ]
    assert registered_readiness["executor_registration"]["executor_registered"] is True

    handoff_response = client.post(
        "/admin/wearables/provider-live-executor-handoff",
        json={
            "request_plan_path": request_plan_payload["request_plan_path"],
            "executor_registration_path": registration_payload["executor_registration_path"],
        },
    )
    assert handoff_response.status_code == 200
    handoff_payload = handoff_response.json()
    handoff = handoff_payload["executor_handoff"]
    handoff_serialized = json.dumps(handoff_payload)

    assert handoff_payload["artifact_kind"] == "scout_wearable_provider_live_executor_handoff_package_result"
    assert Path(handoff_payload["executor_handoff_path"]).exists()
    assert handoff["source_provider"] == "garmin_health_api_live"
    assert handoff["request_descriptor_count"] == 2
    assert handoff["transport"]["network_request_performed"] is False
    assert handoff["transport"]["real_provider_api_called"] is False
    assert handoff["transport"]["runtime_ingest_performed"] is False
    assert handoff["boundary"]["medical_diagnosis"] is False
    assert handoff["boundary"]["phase1_runtime_safety_truth"] is False
    assert "admin.garmin.executor.private" not in handoff_serialized
    assert "secret-token-value" not in handoff_serialized
    assert "garmin.account.private" not in handoff_serialized
    assert "garmin.watch.private" not in handoff_serialized
    assert "/safety/" not in handoff_serialized

    handoff_outbox_dir = tmp_path / "admin-garmin-executor-handoff-outbox"
    handoff_outbox_dir.mkdir()
    (handoff_outbox_dir / "garmin-executor-handoff.json").write_text(
        Path(handoff_payload["executor_handoff_path"]).read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    (handoff_outbox_dir / "unrelated.json").write_text(
        json.dumps({"artifact_kind": "unrelated_local_artifact"}),
        encoding="utf-8",
    )
    handoff_outbox_index_response = client.post(
        "/admin/wearables/provider-live-index-executor-handoff-outbox",
        json={"outbox_dir": str(handoff_outbox_dir)},
    )
    assert handoff_outbox_index_response.status_code == 200
    handoff_outbox_index_payload = handoff_outbox_index_response.json()
    handoff_outbox_index = handoff_outbox_index_payload["executor_handoff_outbox_index"]
    handoff_outbox_index_serialized = json.dumps(handoff_outbox_index_payload)

    assert (
        handoff_outbox_index_payload["artifact_kind"]
        == "scout_wearable_provider_live_executor_handoff_outbox_index_result"
    )
    assert Path(handoff_outbox_index_payload["executor_handoff_outbox_index_path"]).exists()
    assert handoff_outbox_index["source_provider"] == "garmin_health_api_live"
    assert handoff_outbox_index["outbox"]["json_file_count"] == 2
    assert handoff_outbox_index["outbox"]["eligible_handoff_count"] == 1
    assert handoff_outbox_index["outbox"]["rejected_file_count"] == 1
    assert handoff_outbox_index["transport"]["network_request_performed"] is False
    assert handoff_outbox_index["transport"]["real_provider_api_called"] is False
    assert handoff_outbox_index["transport"]["runtime_ingest_performed"] is False
    assert handoff_outbox_index["mutation"]["outbox_file_mutated"] is False
    assert "admin.garmin.executor.private" not in handoff_outbox_index_serialized
    assert "secret-token-value" not in handoff_outbox_index_serialized
    assert "garmin.account.private" not in handoff_outbox_index_serialized
    assert "garmin.watch.private" not in handoff_outbox_index_serialized
    assert "/safety/" not in handoff_outbox_index_serialized

    handoff_pickup_response = client.post(
        "/admin/wearables/provider-live-executor-handoff-pickup-manifest",
        json={
            "outbox_index_path": handoff_outbox_index_payload[
                "executor_handoff_outbox_index_path"
            ],
        },
    )
    assert handoff_pickup_response.status_code == 200
    handoff_pickup_payload = handoff_pickup_response.json()
    handoff_pickup = handoff_pickup_payload["executor_handoff_pickup_manifest"]
    handoff_pickup_serialized = json.dumps(handoff_pickup_payload)

    assert (
        handoff_pickup_payload["artifact_kind"]
        == "scout_wearable_provider_live_executor_handoff_pickup_manifest_result"
    )
    assert Path(handoff_pickup_payload["executor_handoff_pickup_manifest_path"]).exists()
    assert handoff_pickup["source_provider"] == "garmin_health_api_live"
    assert handoff_pickup["pickup"]["pickup_status"] == "ready_for_external_executor_review"
    assert handoff_pickup["pickup"]["external_execution_authorized"] is False
    assert handoff_pickup["transport"]["network_request_performed"] is False
    assert handoff_pickup["transport"]["real_provider_api_called"] is False
    assert handoff_pickup["transport"]["runtime_ingest_performed"] is False
    assert handoff_pickup["mutation"]["outbox_file_mutated"] is False
    assert "admin.garmin.executor.private" not in handoff_pickup_serialized
    assert "secret-token-value" not in handoff_pickup_serialized
    assert "garmin.account.private" not in handoff_pickup_serialized
    assert "garmin.watch.private" not in handoff_pickup_serialized
    assert "/safety/" not in handoff_pickup_serialized

    response_fixture_path = _write_garmin_health_api_response_fixture(tmp_path / "garmin-response.json")
    pickup_response_manifest_response = client.post(
        "/admin/wearables/provider-live-executor-pickup-response-manifest",
        json={
            "pickup_manifest_path": handoff_pickup_payload[
                "executor_handoff_pickup_manifest_path"
            ],
            "response_payload_path": str(response_fixture_path),
        },
    )
    assert pickup_response_manifest_response.status_code == 200
    pickup_response_manifest_payload = pickup_response_manifest_response.json()
    pickup_response_manifest = pickup_response_manifest_payload["executor_response_manifest"]
    pickup_response_manifest_serialized = json.dumps(pickup_response_manifest_payload)

    assert (
        pickup_response_manifest_payload["artifact_kind"]
        == "scout_wearable_provider_live_executor_pickup_response_manifest_result"
    )
    assert Path(pickup_response_manifest_payload["executor_response_manifest_path"]).exists()
    assert pickup_response_manifest["source_provider"] == "garmin_health_api_live"
    assert pickup_response_manifest["pickup_manifest"]["sha256"] == handoff_pickup["sha256"]
    assert pickup_response_manifest["pickup_manifest"]["external_execution_authorized"] is False
    assert pickup_response_manifest["transport"]["network_request_performed"] is False
    assert pickup_response_manifest["transport"]["real_provider_api_called"] is False
    assert pickup_response_manifest["transport"]["runtime_ingest_performed"] is False
    assert pickup_response_manifest["response_payload"]["raw_response_embedded"] is False
    assert "admin.garmin.executor.private" not in pickup_response_manifest_serialized
    assert "secret-token-value" not in pickup_response_manifest_serialized
    assert "garmin.account.private" not in pickup_response_manifest_serialized
    assert "garmin.watch.private" not in pickup_response_manifest_serialized
    assert "heartRateSamples" not in pickup_response_manifest_serialized
    assert "geoPolylineDTO" not in pickup_response_manifest_serialized
    assert "/safety/" not in pickup_response_manifest_serialized

    pickup_response_consumption_response = client.post(
        "/admin/wearables/provider-live-consume-executor-pickup-response",
        json={
            "executor_response_manifest_path": pickup_response_manifest_payload[
                "executor_response_manifest_path"
            ],
            "activity_id_prefix": "admin.live.garmin.executor.pickup.response.consumed",
            "capabilities": ["activity_summary_import", "provider_body_energy_source_values"],
            "reference_date": "2026-05-27",
        },
    )
    assert pickup_response_consumption_response.status_code == 200
    pickup_response_consumption_payload = pickup_response_consumption_response.json()
    pickup_response_consumption = pickup_response_consumption_payload[
        "executor_pickup_response_consumption"
    ]
    pickup_response_consumption_serialized = json.dumps(pickup_response_consumption_payload)

    assert (
        pickup_response_consumption_payload["artifact_kind"]
        == "scout_wearable_provider_live_executor_pickup_response_consumption_result"
    )
    assert Path(
        pickup_response_consumption_payload["executor_pickup_response_consumption_path"]
    ).exists()
    assert Path(pickup_response_consumption_payload["baseline_path"]).exists()
    assert pickup_response_consumption["source_provider"] == "garmin_health_api_live"
    assert pickup_response_consumption["pickup_manifest"]["sha256"] == handoff_pickup["sha256"]
    assert (
        pickup_response_consumption_payload["executor_response_consumption"][
            "executor_response_manifest"
        ]["pickup_manifest_sha256"]
        == handoff_pickup["sha256"]
    )
    assert pickup_response_consumption["transport"]["network_request_performed"] is False
    assert pickup_response_consumption["transport"]["real_provider_api_called"] is False
    assert pickup_response_consumption["transport"]["runtime_ingest_performed"] is False
    assert pickup_response_consumption["boundary"]["medical_diagnosis"] is False
    assert pickup_response_consumption["boundary"]["phase1_runtime_safety_truth"] is False
    assert "admin.garmin.executor.private" not in pickup_response_consumption_serialized
    assert "secret-token-value" not in pickup_response_consumption_serialized
    assert "garmin.account.private" not in pickup_response_consumption_serialized
    assert "garmin.watch.private" not in pickup_response_consumption_serialized
    assert "heartRateSamples" not in pickup_response_consumption_serialized
    assert "geoPolylineDTO" not in pickup_response_consumption_serialized
    assert "/safety/" not in pickup_response_consumption_serialized

    pickup_response_receipt_response = client.post(
        "/admin/wearables/provider-live-executor-pickup-response-consumption-receipt",
        json={
            "pickup_response_consumption_path": pickup_response_consumption_payload[
                "executor_pickup_response_consumption_path"
            ],
        },
    )
    assert pickup_response_receipt_response.status_code == 200
    pickup_response_receipt_payload = pickup_response_receipt_response.json()
    pickup_response_receipt = pickup_response_receipt_payload[
        "executor_pickup_response_consumption_receipt"
    ]
    pickup_response_receipt_serialized = json.dumps(pickup_response_receipt_payload)

    assert (
        pickup_response_receipt_payload["artifact_kind"]
        == "scout_wearable_provider_live_executor_pickup_response_consumption_receipt_result"
    )
    assert Path(
        pickup_response_receipt_payload["executor_pickup_response_consumption_receipt_path"]
    ).exists()
    assert pickup_response_receipt["source_provider"] == "garmin_health_api_live"
    assert (
        pickup_response_receipt["pickup_response_consumption"]["sha256"]
        == pickup_response_consumption["sha256"]
    )
    assert pickup_response_receipt["pickup_manifest"]["sha256"] == handoff_pickup["sha256"]
    assert pickup_response_receipt["receipt"]["receipt_status"] == "locally_recorded"
    assert pickup_response_receipt["transport"]["network_request_performed"] is False
    assert pickup_response_receipt["transport"]["real_provider_api_called"] is False
    assert pickup_response_receipt["transport"]["runtime_ingest_performed"] is False
    assert pickup_response_receipt["mutation"]["outbox_file_mutated"] is False
    assert pickup_response_receipt["mutation"]["inbox_file_mutated"] is False
    assert "admin.garmin.executor.private" not in pickup_response_receipt_serialized
    assert "secret-token-value" not in pickup_response_receipt_serialized
    assert "garmin.account.private" not in pickup_response_receipt_serialized
    assert "garmin.watch.private" not in pickup_response_receipt_serialized
    assert "heartRateSamples" not in pickup_response_receipt_serialized
    assert "geoPolylineDTO" not in pickup_response_receipt_serialized
    assert "/safety/" not in pickup_response_receipt_serialized

    pickup_status_snapshot_response = client.post(
        "/admin/wearables/provider-live-executor-pickup-status-snapshot",
        json={
            "pickup_manifest_path": handoff_pickup_payload[
                "executor_handoff_pickup_manifest_path"
            ],
            "executor_response_manifest_path": pickup_response_manifest_payload[
                "executor_response_manifest_path"
            ],
            "pickup_response_consumption_path": pickup_response_consumption_payload[
                "executor_pickup_response_consumption_path"
            ],
            "pickup_response_receipt_path": pickup_response_receipt_payload[
                "executor_pickup_response_consumption_receipt_path"
            ],
        },
    )
    assert pickup_status_snapshot_response.status_code == 200
    pickup_status_snapshot_payload = pickup_status_snapshot_response.json()
    pickup_status_snapshot = pickup_status_snapshot_payload["executor_pickup_status_snapshot"]
    pickup_status_snapshot_serialized = json.dumps(pickup_status_snapshot_payload)

    assert (
        pickup_status_snapshot_payload["artifact_kind"]
        == "scout_wearable_provider_live_executor_pickup_status_snapshot_result"
    )
    assert Path(pickup_status_snapshot_payload["executor_pickup_status_snapshot_path"]).exists()
    assert pickup_status_snapshot_payload["pickup_lifecycle_status"] == "receipt_recorded"
    assert pickup_status_snapshot["source_provider"] == "garmin_health_api_live"
    assert pickup_status_snapshot["pickup_manifest"]["sha256"] == handoff_pickup["sha256"]
    assert pickup_status_snapshot["status"]["local_evidence_complete"] is True
    assert pickup_status_snapshot["status"]["runtime_safety_truth"] is False
    assert pickup_status_snapshot["transport"]["network_request_performed"] is False
    assert pickup_status_snapshot["transport"]["real_provider_api_called"] is False
    assert pickup_status_snapshot["transport"]["runtime_ingest_performed"] is False
    assert pickup_status_snapshot["mutation"]["outbox_file_mutated"] is False
    assert pickup_status_snapshot["mutation"]["inbox_file_mutated"] is False
    assert "admin.garmin.executor.private" not in pickup_status_snapshot_serialized
    assert "secret-token-value" not in pickup_status_snapshot_serialized
    assert "garmin.account.private" not in pickup_status_snapshot_serialized
    assert "garmin.watch.private" not in pickup_status_snapshot_serialized
    assert "heartRateSamples" not in pickup_status_snapshot_serialized
    assert "geoPolylineDTO" not in pickup_status_snapshot_serialized
    assert "/safety/" not in pickup_status_snapshot_serialized

    handoff_replay_response = client.post(
        "/admin/wearables/provider-live-handoff-fixture-replay",
        json={
            "executor_handoff_path": handoff_payload["executor_handoff_path"],
            "response_fixture_path": str(response_fixture_path),
        },
    )
    assert handoff_replay_response.status_code == 200
    handoff_replay_payload = handoff_replay_response.json()
    handoff_replay = handoff_replay_payload["executor_fixture_replay"]
    handoff_replay_serialized = json.dumps(handoff_replay_payload)

    assert (
        handoff_replay_payload["artifact_kind"]
        == "scout_wearable_provider_live_executor_handoff_fixture_replay_result"
    )
    assert Path(handoff_replay_payload["executor_fixture_replay_path"]).exists()
    assert handoff_replay["source_provider"] == "garmin_health_api_live"
    assert handoff_replay["handoff_package"]["sha256"] == handoff["sha256"]
    assert handoff_replay["response_fixture"]["raw_response_embedded"] is False
    assert handoff_replay["transport"]["network_request_performed"] is False
    assert handoff_replay["transport"]["real_provider_api_called"] is False
    assert handoff_replay["transport"]["runtime_ingest_performed"] is False
    assert handoff_replay["boundary"]["medical_diagnosis"] is False
    assert handoff_replay["boundary"]["phase1_runtime_safety_truth"] is False
    assert "admin.garmin.executor.private" not in handoff_replay_serialized
    assert "secret-token-value" not in handoff_replay_serialized
    assert "garmin.account.private" not in handoff_replay_serialized
    assert "garmin.watch.private" not in handoff_replay_serialized
    assert "heartRateSamples" not in handoff_replay_serialized
    assert "geoPolylineDTO" not in handoff_replay_serialized
    assert "/safety/" not in handoff_replay_serialized

    response_manifest_response = client.post(
        "/admin/wearables/provider-live-executor-response-manifest",
        json={
            "executor_handoff_path": handoff_payload["executor_handoff_path"],
            "response_payload_path": str(response_fixture_path),
        },
    )
    assert response_manifest_response.status_code == 200
    response_manifest_payload = response_manifest_response.json()
    response_manifest = response_manifest_payload["executor_response_manifest"]
    response_manifest_serialized = json.dumps(response_manifest_payload)

    assert (
        response_manifest_payload["artifact_kind"]
        == "scout_wearable_provider_live_executor_response_manifest_result"
    )
    assert Path(response_manifest_payload["executor_response_manifest_path"]).exists()
    assert response_manifest["source_provider"] == "garmin_health_api_live"
    assert response_manifest["handoff_package"]["sha256"] == handoff["sha256"]
    assert response_manifest["response_payload"]["raw_response_embedded"] is False
    assert response_manifest["transport"]["network_request_performed"] is False
    assert response_manifest["transport"]["real_provider_api_called"] is False
    assert response_manifest["transport"]["runtime_ingest_performed"] is False
    assert response_manifest["boundary"]["medical_diagnosis"] is False
    assert response_manifest["boundary"]["phase1_runtime_safety_truth"] is False
    assert "admin.garmin.executor.private" not in response_manifest_serialized
    assert "secret-token-value" not in response_manifest_serialized
    assert "garmin.account.private" not in response_manifest_serialized
    assert "garmin.watch.private" not in response_manifest_serialized
    assert "heartRateSamples" not in response_manifest_serialized
    assert "geoPolylineDTO" not in response_manifest_serialized
    assert "/safety/" not in response_manifest_serialized

    response_inbox_dir = tmp_path / "admin-executor-response-inbox"
    response_inbox_dir.mkdir()
    (response_inbox_dir / "garmin-response-manifest.json").write_text(
        Path(response_manifest_payload["executor_response_manifest_path"]).read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    inbox_index_response = client.post(
        "/admin/wearables/provider-live-index-executor-response-inbox",
        json={"inbox_dir": str(response_inbox_dir)},
    )
    assert inbox_index_response.status_code == 200
    inbox_index_payload = inbox_index_response.json()
    inbox_index = inbox_index_payload["executor_response_inbox_index"]
    inbox_index_serialized = json.dumps(inbox_index_payload)

    assert inbox_index_payload["artifact_kind"] == "scout_wearable_provider_live_executor_response_inbox_index_result"
    assert Path(inbox_index_payload["executor_response_inbox_index_path"]).exists()
    assert inbox_index["source_provider"] == "garmin_health_api_live"
    assert inbox_index["inbox"]["eligible_manifest_count"] == 1
    assert inbox_index["manifests"][0]["eligible_for_consumption_precheck"] is True
    assert inbox_index["manifests"][0]["handoff_ref_valid"] is True
    assert inbox_index["manifests"][0]["response_payload_ref_valid"] is True
    assert inbox_index["transport"]["network_request_performed"] is False
    assert inbox_index["transport"]["real_provider_api_called"] is False
    assert inbox_index["transport"]["runtime_ingest_performed"] is False
    assert "admin.garmin.executor.private" not in inbox_index_serialized
    assert "secret-token-value" not in inbox_index_serialized
    assert "garmin.account.private" not in inbox_index_serialized
    assert "garmin.watch.private" not in inbox_index_serialized
    assert "heartRateSamples" not in inbox_index_serialized
    assert "geoPolylineDTO" not in inbox_index_serialized
    assert "/safety/" not in inbox_index_serialized

    inbox_consumption_response = client.post(
        "/admin/wearables/provider-live-consume-executor-response-inbox",
        json={
            "inbox_index_path": inbox_index_payload["executor_response_inbox_index_path"],
            "activity_id_prefix": "admin.live.garmin.executor.response.inbox.consumed",
            "capabilities": ["activity_summary_import", "provider_body_energy_source_values"],
            "reference_date": "2026-05-27",
        },
    )
    assert inbox_consumption_response.status_code == 200
    inbox_consumption_payload = inbox_consumption_response.json()
    inbox_consumption = inbox_consumption_payload["executor_response_inbox_consumption"]
    inbox_consumption_serialized = json.dumps(inbox_consumption_payload)

    assert (
        inbox_consumption_payload["artifact_kind"]
        == "scout_wearable_provider_live_executor_response_inbox_consumption_result"
    )
    assert Path(inbox_consumption_payload["executor_response_inbox_consumption_path"]).exists()
    assert Path(inbox_consumption_payload["baseline_path"]).exists()
    assert inbox_consumption["source_provider"] == "garmin_health_api_live"
    assert inbox_consumption["selected_manifest"]["source_path"] == str(
        response_inbox_dir / "garmin-response-manifest.json"
    )
    assert inbox_consumption["executor_response_consumption"]["artifact_kind"] == (
        "scout_wearable_provider_live_executor_response_consumption"
    )
    assert inbox_consumption["transport"]["network_request_performed"] is False
    assert inbox_consumption["transport"]["real_provider_api_called"] is False
    assert inbox_consumption["transport"]["runtime_ingest_performed"] is False
    assert "admin.garmin.executor.private" not in inbox_consumption_serialized
    assert "secret-token-value" not in inbox_consumption_serialized
    assert "garmin.account.private" not in inbox_consumption_serialized
    assert "garmin.watch.private" not in inbox_consumption_serialized
    assert "heartRateSamples" not in inbox_consumption_serialized
    assert "geoPolylineDTO" not in inbox_consumption_serialized
    assert "/safety/" not in inbox_consumption_serialized

    inbox_batch_consumption_response = client.post(
        "/admin/wearables/provider-live-consume-executor-response-inbox-batch",
        json={
            "inbox_index_path": inbox_index_payload["executor_response_inbox_index_path"],
            "activity_id_prefix": "admin.live.garmin.executor.response.inbox.batch.consumed",
            "capabilities": ["activity_summary_import", "provider_body_energy_source_values"],
            "reference_date": "2026-05-27",
        },
    )
    assert inbox_batch_consumption_response.status_code == 200
    inbox_batch_consumption_payload = inbox_batch_consumption_response.json()
    inbox_batch_consumption = inbox_batch_consumption_payload["executor_response_inbox_batch_consumption"]
    inbox_batch_consumption_serialized = json.dumps(inbox_batch_consumption_payload)

    assert (
        inbox_batch_consumption_payload["artifact_kind"]
        == "scout_wearable_provider_live_executor_response_inbox_batch_consumption_result"
    )
    assert Path(inbox_batch_consumption_payload["executor_response_inbox_batch_consumption_path"]).exists()
    assert inbox_batch_consumption_payload["consumed_manifest_count"] == 1
    assert inbox_batch_consumption["source_provider"] == "garmin_health_api_live"
    assert inbox_batch_consumption["batch"]["consumed_manifest_count"] == 1
    assert inbox_batch_consumption["transport"]["network_request_performed"] is False
    assert inbox_batch_consumption["transport"]["real_provider_api_called"] is False
    assert inbox_batch_consumption["transport"]["runtime_ingest_performed"] is False
    assert "admin.garmin.executor.private" not in inbox_batch_consumption_serialized
    assert "secret-token-value" not in inbox_batch_consumption_serialized
    assert "garmin.account.private" not in inbox_batch_consumption_serialized
    assert "garmin.watch.private" not in inbox_batch_consumption_serialized
    assert "heartRateSamples" not in inbox_batch_consumption_serialized
    assert "geoPolylineDTO" not in inbox_batch_consumption_serialized
    assert "/safety/" not in inbox_batch_consumption_serialized

    inbox_batch_receipt_response = client.post(
        "/admin/wearables/provider-live-executor-response-inbox-batch-receipt",
        json={
            "batch_consumption_path": inbox_batch_consumption_payload[
                "executor_response_inbox_batch_consumption_path"
            ],
        },
    )
    assert inbox_batch_receipt_response.status_code == 200
    inbox_batch_receipt_payload = inbox_batch_receipt_response.json()
    inbox_batch_receipt = inbox_batch_receipt_payload["executor_response_inbox_batch_receipt"]
    inbox_batch_receipt_serialized = json.dumps(inbox_batch_receipt_payload)

    assert (
        inbox_batch_receipt_payload["artifact_kind"]
        == "scout_wearable_provider_live_executor_response_inbox_batch_receipt_result"
    )
    assert Path(inbox_batch_receipt_payload["executor_response_inbox_batch_receipt_path"]).exists()
    assert inbox_batch_receipt_payload["consumed_manifest_count"] == 1
    assert inbox_batch_receipt["source_provider"] == "garmin_health_api_live"
    assert inbox_batch_receipt["batch_consumption"]["consumed_manifest_count"] == 1
    assert inbox_batch_receipt["transport"]["network_request_performed"] is False
    assert inbox_batch_receipt["transport"]["real_provider_api_called"] is False
    assert inbox_batch_receipt["transport"]["runtime_ingest_performed"] is False
    assert inbox_batch_receipt["mutation"]["inbox_file_mutated"] is False
    assert inbox_batch_receipt["receipts"][0]["receipt_status"] == "locally_recorded"
    assert "admin.garmin.executor.private" not in inbox_batch_receipt_serialized
    assert "secret-token-value" not in inbox_batch_receipt_serialized
    assert "garmin.account.private" not in inbox_batch_receipt_serialized
    assert "garmin.watch.private" not in inbox_batch_receipt_serialized
    assert "heartRateSamples" not in inbox_batch_receipt_serialized
    assert "geoPolylineDTO" not in inbox_batch_receipt_serialized
    assert "/safety/" not in inbox_batch_receipt_serialized

    inbox_status_snapshot_response = client.post(
        "/admin/wearables/provider-live-executor-response-inbox-status-snapshot",
        json={
            "inbox_index_path": inbox_index_payload["executor_response_inbox_index_path"],
            "batch_consumption_path": inbox_batch_consumption_payload[
                "executor_response_inbox_batch_consumption_path"
            ],
            "batch_receipt_path": inbox_batch_receipt_payload[
                "executor_response_inbox_batch_receipt_path"
            ],
        },
    )
    assert inbox_status_snapshot_response.status_code == 200
    inbox_status_snapshot_payload = inbox_status_snapshot_response.json()
    inbox_status_snapshot = inbox_status_snapshot_payload["executor_response_inbox_status_snapshot"]
    inbox_status_snapshot_serialized = json.dumps(inbox_status_snapshot_payload)

    assert (
        inbox_status_snapshot_payload["artifact_kind"]
        == "scout_wearable_provider_live_executor_response_inbox_status_snapshot_result"
    )
    assert Path(inbox_status_snapshot_payload["executor_response_inbox_status_snapshot_path"]).exists()
    assert inbox_status_snapshot_payload["manifest_status_counts"]["receipt_recorded_manifest_count"] == 1
    assert inbox_status_snapshot["source_provider"] == "garmin_health_api_live"
    assert inbox_status_snapshot["manifest_statuses"][0]["manifest_status"] == "receipt_recorded"
    assert inbox_status_snapshot["transport"]["network_request_performed"] is False
    assert inbox_status_snapshot["transport"]["real_provider_api_called"] is False
    assert inbox_status_snapshot["transport"]["runtime_ingest_performed"] is False
    assert inbox_status_snapshot["mutation"]["inbox_file_mutated"] is False
    assert "admin.garmin.executor.private" not in inbox_status_snapshot_serialized
    assert "secret-token-value" not in inbox_status_snapshot_serialized
    assert "garmin.account.private" not in inbox_status_snapshot_serialized
    assert "garmin.watch.private" not in inbox_status_snapshot_serialized
    assert "heartRateSamples" not in inbox_status_snapshot_serialized
    assert "geoPolylineDTO" not in inbox_status_snapshot_serialized
    assert "/safety/" not in inbox_status_snapshot_serialized

    lifecycle_audit_response = client.post(
        "/admin/wearables/provider-live-executor-lifecycle-audit",
        json={
            "pickup_status_snapshot_path": pickup_status_snapshot_payload[
                "executor_pickup_status_snapshot_path"
            ],
            "inbox_status_snapshot_path": inbox_status_snapshot_payload[
                "executor_response_inbox_status_snapshot_path"
            ],
        },
    )
    assert lifecycle_audit_response.status_code == 200
    lifecycle_audit_payload = lifecycle_audit_response.json()
    lifecycle_audit = lifecycle_audit_payload["executor_lifecycle_audit"]
    lifecycle_audit_serialized = json.dumps(lifecycle_audit_payload)

    assert (
        lifecycle_audit_payload["artifact_kind"]
        == "scout_wearable_provider_live_executor_lifecycle_audit_result"
    )
    assert Path(lifecycle_audit_payload["executor_lifecycle_audit_path"]).exists()
    assert lifecycle_audit_payload["local_executor_lifecycle_status"] == "local_evidence_complete"
    assert lifecycle_audit["source_provider"] == "garmin_health_api_live"
    assert lifecycle_audit["lifecycle"]["pickup_local_evidence_complete"] is True
    assert lifecycle_audit["lifecycle"]["inbox_local_evidence_complete"] is True
    assert lifecycle_audit["lifecycle"]["runtime_safety_truth"] is False
    assert lifecycle_audit["transport"]["network_request_performed"] is False
    assert lifecycle_audit["transport"]["real_provider_api_called"] is False
    assert lifecycle_audit["transport"]["runtime_ingest_performed"] is False
    assert lifecycle_audit["mutation"]["outbox_file_mutated"] is False
    assert lifecycle_audit["mutation"]["inbox_file_mutated"] is False
    assert "admin.garmin.executor.private" not in lifecycle_audit_serialized
    assert "secret-token-value" not in lifecycle_audit_serialized
    assert "garmin.account.private" not in lifecycle_audit_serialized
    assert "garmin.watch.private" not in lifecycle_audit_serialized
    assert "heartRateSamples" not in lifecycle_audit_serialized
    assert "geoPolylineDTO" not in lifecycle_audit_serialized
    assert "/safety/" not in lifecycle_audit_serialized

    credential_vault_reference_response = client.post(
        "/admin/wearables/provider-live-credential-vault-reference",
        json={
            "provider": "garmin_health_api_live",
            "vault_ref": "admin.garmin.vault.private",
            "account_ref": "garmin.account.private",
            "device_ref": "garmin.watch.private",
            "token_ref": "secret-token-value",
            "scopes": ["activity:read", "heart_rate:read", "body_energy:read"],
            "capabilities": [
                "activity_summary_import",
                "heart_rate_samples",
                "provider_body_energy_source_values",
            ],
            "explicit_consent": True,
        },
    )
    assert credential_vault_reference_response.status_code == 200
    credential_vault_reference_payload = credential_vault_reference_response.json()
    credential_vault_reference = credential_vault_reference_payload[
        "credential_vault_reference"
    ]
    credential_vault_reference_serialized = json.dumps(credential_vault_reference_payload)

    assert (
        credential_vault_reference_payload["artifact_kind"]
        == "scout_wearable_provider_live_credential_vault_reference_result"
    )
    assert Path(credential_vault_reference_payload["credential_vault_reference_path"]).exists()
    assert credential_vault_reference["source_provider"] == "garmin_health_api_live"
    assert credential_vault_reference["credential_vault"]["credential_values_loaded"] is False
    assert credential_vault_reference["credential_vault"]["credential_values_exposed"] is False
    assert credential_vault_reference["transport"]["network_request_performed"] is False
    assert credential_vault_reference["transport"]["real_provider_api_called"] is False
    assert credential_vault_reference["transport"]["runtime_ingest_performed"] is False
    assert "admin.garmin.vault.private" not in credential_vault_reference_serialized
    assert "secret-token-value" not in credential_vault_reference_serialized
    assert "garmin.account.private" not in credential_vault_reference_serialized
    assert "garmin.watch.private" not in credential_vault_reference_serialized
    assert "/safety/" not in credential_vault_reference_serialized

    connector_reference_response = client.post(
        "/admin/wearables/provider-live-connector-reference",
        json={
            "provider": "garmin_health_api_live",
            "connector_kind": "garmin_health_api_connector",
            "connector_ref": "admin.garmin.connector.private",
            "connector_version": "garmin-connector-0.1.0",
            "connector_binary_ref": "admin.garmin.connector.binary.private",
            "capabilities": [
                "activity_summary_import",
                "heart_rate_samples",
                "provider_body_energy_source_values",
            ],
            "explicit_consent": True,
        },
    )
    assert connector_reference_response.status_code == 200
    connector_reference_payload = connector_reference_response.json()
    connector_reference = connector_reference_payload["connector_reference"]
    connector_reference_serialized = json.dumps(connector_reference_payload)

    assert (
        connector_reference_payload["artifact_kind"]
        == "scout_wearable_provider_live_connector_reference_result"
    )
    assert Path(connector_reference_payload["connector_reference_path"]).exists()
    assert connector_reference["source_provider"] == "garmin_health_api_live"
    assert connector_reference["connector"]["connector_kind"] == "garmin_health_api_connector"
    assert connector_reference["connector"]["connector_process_started"] is False
    assert connector_reference["connector"]["connector_health_check_performed"] is False
    assert connector_reference["connector"]["connector_live_request_performed"] is False
    assert connector_reference["connector"]["connector_execution_bound"] is False
    assert connector_reference["transport"]["network_request_performed"] is False
    assert connector_reference["transport"]["real_provider_api_called"] is False
    assert connector_reference["transport"]["runtime_ingest_performed"] is False
    assert "admin.garmin.connector.private" not in connector_reference_serialized
    assert "admin.garmin.connector.binary.private" not in connector_reference_serialized
    assert "/safety/" not in connector_reference_serialized

    network_policy_reference_response = client.post(
        "/admin/wearables/provider-live-network-policy-reference",
        json={
            "provider": "garmin_health_api_live",
            "policy_ref": "admin.garmin.network.policy.private",
            "endpoint_ref": "admin.garmin.endpoint.private",
            "egress_profile_ref": "admin.garmin.egress.private",
            "tls_profile_ref": "admin.garmin.tls.private",
            "capabilities": [
                "activity_summary_import",
                "heart_rate_samples",
                "provider_body_energy_source_values",
            ],
            "explicit_consent": True,
        },
    )
    assert network_policy_reference_response.status_code == 200
    network_policy_reference_payload = network_policy_reference_response.json()
    network_policy_reference = network_policy_reference_payload["network_policy_reference"]
    network_policy_reference_serialized = json.dumps(network_policy_reference_payload)

    assert (
        network_policy_reference_payload["artifact_kind"]
        == "scout_wearable_provider_live_network_policy_reference_result"
    )
    assert Path(network_policy_reference_payload["network_policy_reference_path"]).exists()
    assert network_policy_reference["source_provider"] == "garmin_health_api_live"
    assert network_policy_reference["network_policy"]["dns_lookup_performed"] is False
    assert network_policy_reference["network_policy"]["network_socket_opened"] is False
    assert network_policy_reference["network_policy"]["http_request_performed"] is False
    assert network_policy_reference["network_policy"]["network_request_performed"] is False
    assert network_policy_reference["network_policy"]["real_provider_api_called"] is False
    assert network_policy_reference["transport"]["network_request_performed"] is False
    assert network_policy_reference["transport"]["real_provider_api_called"] is False
    assert network_policy_reference["transport"]["runtime_ingest_performed"] is False
    assert "admin.garmin.network.policy.private" not in network_policy_reference_serialized
    assert "admin.garmin.endpoint.private" not in network_policy_reference_serialized
    assert "admin.garmin.egress.private" not in network_policy_reference_serialized
    assert "admin.garmin.tls.private" not in network_policy_reference_serialized
    assert "/safety/" not in network_policy_reference_serialized

    runtime_ingest_boundary_reference_response = client.post(
        "/admin/wearables/provider-live-runtime-ingest-boundary-reference",
        json={
            "provider": "garmin_health_api_live",
            "runtime_boundary_ref": "admin.phase1.runtime.boundary.private",
            "runtime_channel_ref": "admin.energy.advisory.channel.private",
            "artifact_kinds": [
                "scout_wearable_provider_live_executor_production_readiness_gate",
                "scout_energy_reserve_baseline",
            ],
            "handoff_mode": "advisory_energy_reference_only",
            "explicit_consent": True,
        },
    )
    assert runtime_ingest_boundary_reference_response.status_code == 200
    runtime_ingest_boundary_reference_payload = (
        runtime_ingest_boundary_reference_response.json()
    )
    runtime_ingest_boundary_reference = runtime_ingest_boundary_reference_payload[
        "runtime_ingest_boundary_reference"
    ]
    runtime_ingest_boundary_reference_serialized = json.dumps(
        runtime_ingest_boundary_reference_payload
    )

    assert (
        runtime_ingest_boundary_reference_payload["artifact_kind"]
        == "scout_wearable_provider_live_runtime_ingest_boundary_reference_result"
    )
    assert Path(
        runtime_ingest_boundary_reference_payload[
            "runtime_ingest_boundary_reference_path"
        ]
    ).exists()
    assert runtime_ingest_boundary_reference["source_provider"] == "garmin_health_api_live"
    assert (
        runtime_ingest_boundary_reference["runtime_ingest_boundary"][
            "runtime_ingest_authorized"
        ]
        is False
    )
    assert (
        runtime_ingest_boundary_reference["runtime_ingest_boundary"][
            "phase1_runtime_safety_truth"
        ]
        is False
    )
    assert runtime_ingest_boundary_reference["transport"]["runtime_ingest_performed"] is False
    assert runtime_ingest_boundary_reference["transport"]["safety_api_called"] is False
    assert "admin.phase1.runtime.boundary.private" not in runtime_ingest_boundary_reference_serialized
    assert "admin.energy.advisory.channel.private" not in runtime_ingest_boundary_reference_serialized
    assert "/safety/" not in runtime_ingest_boundary_reference_serialized

    phase1_safety_boundary_reference_response = client.post(
        "/admin/wearables/provider-live-phase1-safety-boundary-reference",
        json={
            "provider": "garmin_health_api_live",
            "phase1_boundary_ref": "admin.phase1.safety.boundary.private",
            "phase1_state_ref": "admin.phase1.l0-l4.state.private",
            "advisory_channel_ref": "admin.energy.advisory.channel.private",
            "artifact_kinds": [
                "scout_wearable_provider_live_executor_production_readiness_gate",
                "scout_energy_reserve_baseline",
            ],
            "explicit_consent": True,
        },
    )
    assert phase1_safety_boundary_reference_response.status_code == 200
    phase1_safety_boundary_reference_payload = (
        phase1_safety_boundary_reference_response.json()
    )
    phase1_safety_boundary_reference = phase1_safety_boundary_reference_payload[
        "phase1_safety_boundary_reference"
    ]
    phase1_safety_boundary_reference_serialized = json.dumps(
        phase1_safety_boundary_reference_payload
    )

    assert (
        phase1_safety_boundary_reference_payload["artifact_kind"]
        == "scout_wearable_provider_live_phase1_safety_boundary_reference_result"
    )
    assert Path(
        phase1_safety_boundary_reference_payload[
            "phase1_safety_boundary_reference_path"
        ]
    ).exists()
    assert phase1_safety_boundary_reference["source_provider"] == "garmin_health_api_live"
    assert (
        phase1_safety_boundary_reference["phase1_safety_boundary"][
            "not_safety_truth"
        ]
        is True
    )
    assert (
        phase1_safety_boundary_reference["phase1_safety_boundary"][
            "phase1_runtime_safety_truth"
        ]
        is False
    )
    assert (
        phase1_safety_boundary_reference["phase1_safety_boundary"][
            "phase1_l0_l4_state_mutated"
        ]
        is False
    )
    assert phase1_safety_boundary_reference["transport"]["safety_api_called"] is False
    assert "admin.phase1.safety.boundary.private" not in phase1_safety_boundary_reference_serialized
    assert "admin.phase1.l0-l4.state.private" not in phase1_safety_boundary_reference_serialized
    assert "admin.energy.advisory.channel.private" not in phase1_safety_boundary_reference_serialized
    assert "/safety/" not in phase1_safety_boundary_reference_serialized

    production_gate_response = client.post(
        "/admin/wearables/provider-live-executor-production-readiness-gate",
        json={
            "lifecycle_audit_path": lifecycle_audit_payload[
                "executor_lifecycle_audit_path"
            ],
            "connector_reference_path": connector_reference_payload[
                "connector_reference_path"
            ],
            "credential_vault_reference_path": credential_vault_reference_payload[
                "credential_vault_reference_path"
            ],
            "network_policy_reference_path": network_policy_reference_payload[
                "network_policy_reference_path"
            ],
            "runtime_ingest_boundary_reference_path": runtime_ingest_boundary_reference_payload[
                "runtime_ingest_boundary_reference_path"
            ],
            "phase1_safety_boundary_reference_path": phase1_safety_boundary_reference_payload[
                "phase1_safety_boundary_reference_path"
            ],
        },
    )
    assert production_gate_response.status_code == 200
    production_gate_payload = production_gate_response.json()
    production_gate = production_gate_payload["executor_production_readiness_gate"]
    production_gate_serialized = json.dumps(production_gate_payload)

    assert (
        production_gate_payload["artifact_kind"]
        == "scout_wearable_provider_live_executor_production_readiness_gate_result"
    )
    assert Path(production_gate_payload["executor_production_readiness_gate_path"]).exists()
    assert production_gate_payload["production_provider_execution_ready"] is False
    assert production_gate["source_provider"] == "garmin_health_api_live"
    assert production_gate["readiness"]["local_evidence_complete"] is True
    assert production_gate["readiness"]["live_provider_connector_reference_present"] is True
    assert production_gate["readiness"]["credential_vault_reference_present"] is True
    assert production_gate["readiness"]["network_policy_reference_present"] is True
    assert production_gate["readiness"]["runtime_ingest_boundary_reference_present"] is True
    assert production_gate["readiness"]["phase1_safety_boundary_reference_present"] is True
    assert production_gate["readiness"]["phase1_runtime_safety_truth"] is False
    assert production_gate["readiness"]["phase1_l0_l4_state_mutated"] is False
    assert production_gate["readiness"]["safety_api_called"] is False
    assert "live_provider_connector_not_implemented" not in production_gate_payload["production_blockers"]
    assert "credential_vault_not_integrated" not in production_gate_payload["production_blockers"]
    assert "network_execution_disabled_by_local_contract" not in production_gate_payload["production_blockers"]
    assert "runtime_ingest_disabled_by_boundary" in production_gate_payload["production_blockers"]
    assert "phase1_runtime_safety_truth_mutation_forbidden" in production_gate_payload["production_blockers"]
    assert production_gate["inputs"]["connector_reference"]["connector_process_started"] is False
    assert production_gate["inputs"]["credential_vault_reference"]["credential_values_loaded"] is False
    assert production_gate["inputs"]["network_policy_reference"]["network_request_performed"] is False
    assert production_gate["inputs"]["runtime_ingest_boundary_reference"]["runtime_ingest_authorized"] is False
    assert production_gate["inputs"]["phase1_safety_boundary_reference"]["not_safety_truth"] is True
    assert (
        production_gate["inputs"]["phase1_safety_boundary_reference"][
            "phase1_l0_l4_state_mutated"
        ]
        is False
    )
    assert production_gate["transport"]["network_request_performed"] is False
    assert production_gate["transport"]["real_provider_api_called"] is False
    assert production_gate["transport"]["runtime_ingest_performed"] is False
    assert production_gate["mutation"]["outbox_file_mutated"] is False
    assert production_gate["mutation"]["inbox_file_mutated"] is False
    assert "admin.garmin.connector.private" not in production_gate_serialized
    assert "admin.garmin.connector.binary.private" not in production_gate_serialized
    assert "admin.garmin.network.policy.private" not in production_gate_serialized
    assert "admin.garmin.endpoint.private" not in production_gate_serialized
    assert "admin.phase1.runtime.boundary.private" not in production_gate_serialized
    assert "admin.phase1.safety.boundary.private" not in production_gate_serialized
    assert "admin.phase1.l0-l4.state.private" not in production_gate_serialized
    assert "admin.energy.advisory.channel.private" not in production_gate_serialized
    assert "admin.garmin.vault.private" not in production_gate_serialized
    assert "admin.garmin.executor.private" not in production_gate_serialized
    assert "secret-token-value" not in production_gate_serialized
    assert "garmin.account.private" not in production_gate_serialized
    assert "garmin.watch.private" not in production_gate_serialized
    assert "heartRateSamples" not in production_gate_serialized
    assert "geoPolylineDTO" not in production_gate_serialized
    assert "/safety/" not in production_gate_serialized

    response_manifest_admission_response = client.post(
        "/admin/wearables/provider-live-executor-response-admit",
        json={
            "executor_response_manifest_path": response_manifest_payload["executor_response_manifest_path"],
            "activity_id_prefix": "admin.live.garmin.executor.response.admitted",
            "capabilities": ["activity_summary_import", "provider_body_energy_source_values"],
        },
    )
    assert response_manifest_admission_response.status_code == 200
    response_manifest_admission_payload = response_manifest_admission_response.json()
    response_manifest_admission = response_manifest_admission_payload["admission"]
    response_manifest_admission_serialized = json.dumps(response_manifest_admission_payload)

    assert (
        response_manifest_admission_payload["artifact_kind"]
        == "scout_wearable_provider_live_executor_response_manifest_admission_result"
    )
    assert Path(response_manifest_admission_payload["admission_path"]).exists()
    assert response_manifest_admission["source_provider"] == "garmin_health_api_live"
    assert response_manifest_admission["sanitized_import_result"]["activity_count"] == 2
    assert all(Path(path).exists() for path in response_manifest_admission_payload["sanitized_import_paths"])
    assert response_manifest_admission_payload["transport"]["network_request_performed"] is False
    assert response_manifest_admission_payload["transport"]["real_provider_api_called"] is False
    assert response_manifest_admission_payload["transport"]["runtime_ingest_performed"] is False
    assert "admin.garmin.executor.private" not in response_manifest_admission_serialized
    assert "secret-token-value" not in response_manifest_admission_serialized
    assert "garmin.account.private" not in response_manifest_admission_serialized
    assert "garmin.watch.private" not in response_manifest_admission_serialized
    assert "heartRateSamples" not in response_manifest_admission_serialized
    assert "geoPolylineDTO" not in response_manifest_admission_serialized
    assert "/safety/" not in response_manifest_admission_serialized

    response_consumption_response = client.post(
        "/admin/wearables/provider-live-consume-executor-response",
        json={
            "executor_response_manifest_path": response_manifest_payload["executor_response_manifest_path"],
            "activity_id_prefix": "admin.live.garmin.executor.response.consumed",
            "capabilities": ["activity_summary_import", "provider_body_energy_source_values"],
            "reference_date": "2026-05-27",
        },
    )
    assert response_consumption_response.status_code == 200
    response_consumption_payload = response_consumption_response.json()
    response_consumption = response_consumption_payload["executor_response_consumption"]
    response_consumption_serialized = json.dumps(response_consumption_payload)

    assert (
        response_consumption_payload["artifact_kind"]
        == "scout_wearable_provider_live_executor_response_consumption_result"
    )
    assert Path(response_consumption_payload["executor_response_consumption_path"]).exists()
    assert Path(response_consumption_payload["baseline_path"]).exists()
    assert response_consumption["source_provider"] == "garmin_health_api_live"
    assert response_consumption["executor_response_manifest"]["sha256"] == response_manifest["sha256"]
    assert response_consumption["admission"]["artifact_kind"] == "scout_wearable_provider_live_transport_response_admission"
    assert response_consumption["materialization"]["artifact_kind"] == "scout_wearable_provider_live_transport_materialization"
    assert response_consumption["sync_package"]["artifact_kind"] == "scout_wearable_provider_live_transport_sync_package"
    assert response_consumption["energy_artifacts"]["baseline"]["activity_count"] == 2
    assert response_consumption["transport"]["network_request_performed"] is False
    assert response_consumption["transport"]["network_sync_performed"] is False
    assert response_consumption["transport"]["real_provider_api_called"] is False
    assert response_consumption["transport"]["runtime_ingest_performed"] is False
    assert response_consumption["boundary"]["medical_diagnosis"] is False
    assert response_consumption["boundary"]["phase1_runtime_safety_truth"] is False
    assert "admin.garmin.executor.private" not in response_consumption_serialized
    assert "secret-token-value" not in response_consumption_serialized
    assert "garmin.account.private" not in response_consumption_serialized
    assert "garmin.watch.private" not in response_consumption_serialized
    assert "heartRateSamples" not in response_consumption_serialized
    assert "geoPolylineDTO" not in response_consumption_serialized
    assert "/safety/" not in response_consumption_serialized

    replay_response = client.post(
        "/admin/wearables/provider-live-fixture-replay",
        json={
            "request_plan_path": request_plan_payload["request_plan_path"],
            "executor_registration_path": registration_payload["executor_registration_path"],
            "response_fixture_path": str(response_fixture_path),
        },
    )
    assert replay_response.status_code == 200
    replay_payload = replay_response.json()
    replay = replay_payload["executor_fixture_replay"]
    replay_serialized = json.dumps(replay_payload)

    assert replay_payload["artifact_kind"] == "scout_wearable_provider_live_executor_fixture_replay_result"
    assert Path(replay_payload["executor_fixture_replay_path"]).exists()
    assert replay["source_provider"] == "garmin_health_api_live"
    assert replay["response_fixture"]["raw_response_embedded"] is False
    assert replay["transport"]["network_request_performed"] is False
    assert replay["transport"]["real_provider_api_called"] is False
    assert replay["transport"]["runtime_ingest_performed"] is False
    assert replay["boundary"]["medical_diagnosis"] is False
    assert replay["boundary"]["phase1_runtime_safety_truth"] is False
    assert "admin.garmin.executor.private" not in replay_serialized
    assert "secret-token-value" not in replay_serialized
    assert "garmin.account.private" not in replay_serialized
    assert "garmin.watch.private" not in replay_serialized
    assert "heartRateSamples" not in replay_serialized
    assert "geoPolylineDTO" not in replay_serialized
    assert "/safety/" not in replay_serialized

    replay_admission_response = client.post(
        "/admin/wearables/provider-live-replay-admit",
        json={
            "fixture_replay_path": handoff_replay_payload["executor_fixture_replay_path"],
            "activity_id_prefix": "admin.live.garmin.replay.admitted",
            "capabilities": ["activity_summary_import", "provider_body_energy_source_values"],
        },
    )
    assert replay_admission_response.status_code == 200
    replay_admission_payload = replay_admission_response.json()
    replay_admission = replay_admission_payload["admission"]
    replay_admission_serialized = json.dumps(replay_admission_payload)

    assert replay_admission_payload["artifact_kind"] == "scout_wearable_provider_live_executor_replay_admission_result"
    assert Path(replay_admission_payload["admission_path"]).exists()
    assert replay_admission["source_provider"] == "garmin_health_api_live"
    assert replay_admission["sanitized_import_result"]["activity_count"] == 2
    assert all(Path(path).exists() for path in replay_admission_payload["sanitized_import_paths"])
    assert replay_admission_payload["transport"]["network_request_performed"] is False
    assert replay_admission_payload["transport"]["real_provider_api_called"] is False
    assert replay_admission_payload["transport"]["runtime_ingest_performed"] is False
    assert replay_admission_payload["mutation"]["safety_api_called"] is False
    assert replay_admission_payload["boundary"]["medical_diagnosis"] is False
    assert replay_admission_payload["boundary"]["phase1_runtime_safety_truth"] is False
    assert "admin.garmin.executor.private" not in replay_admission_serialized
    assert "secret-token-value" not in replay_admission_serialized
    assert "garmin.account.private" not in replay_admission_serialized
    assert "garmin.watch.private" not in replay_admission_serialized
    assert "heartRateSamples" not in replay_admission_serialized
    assert "geoPolylineDTO" not in replay_admission_serialized
    assert "/safety/" not in replay_admission_serialized

    rehearsal_response = client.post(
        "/admin/wearables/provider-live-rehearse-executor",
        json={
            "request_plan_path": request_plan_payload["request_plan_path"],
            "executor_registration_path": registration_payload["executor_registration_path"],
            "response_fixture_path": str(response_fixture_path),
            "activity_id_prefix": "admin.live.garmin.rehearsed",
            "capabilities": ["activity_summary_import", "provider_body_energy_source_values"],
            "reference_date": "2026-05-27",
        },
    )
    assert rehearsal_response.status_code == 200
    rehearsal_payload = rehearsal_response.json()
    rehearsal = rehearsal_payload["executor_rehearsal"]
    rehearsal_serialized = json.dumps(rehearsal_payload)

    assert rehearsal_payload["artifact_kind"] == "scout_wearable_provider_live_executor_rehearsal_result"
    assert Path(rehearsal_payload["executor_rehearsal_path"]).exists()
    assert Path(rehearsal_payload["executor_handoff_path"]).exists()
    assert Path(rehearsal_payload["executor_response_manifest_path"]).exists()
    assert Path(rehearsal_payload["baseline_path"]).exists()
    assert rehearsal["source_provider"] == "garmin_health_api_live"
    assert rehearsal["readiness"]["execution_blockers"] == [
        "network_execution_disabled_by_local_contract"
    ]
    assert rehearsal["energy_artifacts"]["baseline"]["activity_count"] == 2
    assert (
        rehearsal["executor_response_manifest"]["artifact_kind"]
        == "scout_wearable_provider_live_executor_response_manifest"
    )
    assert rehearsal["executor_response_manifest"]["raw_response_embedded"] is False
    assert rehearsal["transport"]["network_request_performed"] is False
    assert rehearsal["transport"]["network_sync_performed"] is False
    assert rehearsal["transport"]["real_provider_api_called"] is False
    assert rehearsal["transport"]["runtime_ingest_performed"] is False
    assert rehearsal["mutation"]["phase1_runtime_mutated"] is False
    assert rehearsal["boundary"]["medical_diagnosis"] is False
    assert rehearsal["boundary"]["phase1_runtime_safety_truth"] is False
    assert "admin.garmin.executor.private" not in rehearsal_serialized
    assert "secret-token-value" not in rehearsal_serialized
    assert "garmin.account.private" not in rehearsal_serialized
    assert "garmin.watch.private" not in rehearsal_serialized
    assert "heartRateSamples" not in rehearsal_serialized
    assert "geoPolylineDTO" not in rehearsal_serialized
    assert "/safety/" not in rehearsal_serialized

    admission_response = client.post(
        "/admin/wearables/provider-live-response-admit",
        json={
            "request_plan_path": request_plan_payload["request_plan_path"],
            "response_fixture_path": str(response_fixture_path),
            "activity_id_prefix": "admin.live.garmin.admitted",
            "capabilities": ["activity_summary_import", "provider_body_energy_source_values"],
        },
    )
    assert admission_response.status_code == 200
    admission_payload = admission_response.json()
    admission = admission_payload["admission"]
    admission_serialized = json.dumps(admission_payload)

    assert admission_payload["artifact_kind"] == "scout_wearable_provider_live_transport_response_admission_result"
    assert Path(admission_payload["admission_path"]).exists()
    assert admission["source_provider"] == "garmin_health_api_live"
    assert admission["sanitized_import_result"]["activity_count"] == 2
    assert all(Path(path).exists() for path in admission_payload["sanitized_import_paths"])
    assert admission["transport"]["network_request_performed"] is False
    assert admission["transport"]["real_provider_api_called"] is False
    assert admission["transport"]["runtime_ingest_performed"] is False
    assert admission["mutation"]["raw_payload_committed"] is False
    assert admission["privacy"]["raw_health_payload_shared"] is False
    assert admission["boundary"]["phase1_runtime_safety_truth"] is False
    assert "secret-token-value" not in admission_serialized
    assert "garmin.account.private" not in admission_serialized
    assert "garmin.watch.private" not in admission_serialized
    assert "heartRateSamples" not in admission_serialized
    assert "geoPolylineDTO" not in admission_serialized

    materialize_response = client.post(
        "/admin/wearables/provider-live-materialize",
        json={
            "admission_path": admission_payload["admission_path"],
            "overwrite": True,
        },
    )
    assert materialize_response.status_code == 200
    materialize_payload = materialize_response.json()
    materialization = materialize_payload["materialization"]
    materialize_serialized = json.dumps(materialize_payload)

    assert materialize_payload["artifact_kind"] == "scout_wearable_provider_live_transport_materialization_result"
    assert Path(materialize_payload["materialization_path"]).exists()
    assert materialization["source_provider"] == "garmin_health_api_live"
    assert materialization["normalization"]["activity_count"] == 2
    assert all(Path(path).exists() for path in materialize_payload["normalized_paths"])
    assert materialization["transport"]["network_request_performed"] is False
    assert materialization["transport"]["real_provider_api_called"] is False
    assert materialization["transport"]["runtime_ingest_performed"] is False
    assert materialization["mutation"]["phase1_runtime_mutated"] is False
    assert materialization["boundary"]["phase1_runtime_safety_truth"] is False
    assert "heartRateSamples" not in materialize_serialized
    assert "geoPolylineDTO" not in materialize_serialized

    sync_package_response = client.post(
        "/admin/wearables/provider-live-sync-package",
        json={
            "materialization_path": materialize_payload["materialization_path"],
        },
    )
    assert sync_package_response.status_code == 200
    sync_package_payload = sync_package_response.json()
    sync_package = sync_package_payload["sync_package"]
    sync_package_serialized = json.dumps(sync_package_payload)

    assert sync_package_payload["artifact_kind"] == "scout_wearable_provider_live_transport_sync_package_result"
    assert Path(sync_package_payload["sync_package_path"]).exists()
    assert sync_package["source_provider"] == "garmin_health_api_live"
    assert sync_package["normalized_summary_count"] == 2
    assert all(item["valid"] is True for item in sync_package["normalized_summaries"])
    assert sync_package["transport"]["network_request_performed"] is False
    assert sync_package["transport"]["network_sync_performed"] is False
    assert sync_package["transport"]["remote_upload_allowed"] is False
    assert sync_package["transport"]["remote_upload_performed"] is False
    assert sync_package["transport"]["runtime_ingest_performed"] is False
    assert sync_package["mutation"]["safety_api_called"] is False
    assert sync_package["boundary"]["medical_diagnosis"] is False
    assert sync_package["boundary"]["phase1_runtime_safety_truth"] is False
    assert "secret-token-value" not in sync_package_serialized
    assert "garmin.account.private" not in sync_package_serialized
    assert "garmin.watch.private" not in sync_package_serialized
    assert "heartRateSamples" not in sync_package_serialized
    assert "geoPolylineDTO" not in sync_package_serialized
    assert "/safety/" not in sync_package_serialized

    energy_build_response = client.post(
        "/admin/wearables/provider-live-build-energy",
        json={
            "sync_package_path": sync_package_payload["sync_package_path"],
            "reference_date": "2026-05-27",
        },
    )
    assert energy_build_response.status_code == 200
    energy_build_payload = energy_build_response.json()
    energy_build_serialized = json.dumps(energy_build_payload)

    assert energy_build_payload["artifact_kind"] == "scout_energy_reserve_provider_sync_package_build_result"
    assert energy_build_payload["source_provider"] == "garmin_health_api_live"
    assert Path(energy_build_payload["baseline_path"]).exists()
    assert Path(energy_build_payload["explanation_path"]).exists()
    assert Path(energy_build_payload["companion_capsule_path"]).exists()
    assert energy_build_payload["energy_artifacts"]["baseline"]["activity_count"] == 2
    assert energy_build_payload["transport"]["network_request_performed"] is False
    assert energy_build_payload["transport"]["network_sync_performed"] is False
    assert energy_build_payload["transport"]["remote_upload_performed"] is False
    assert energy_build_payload["transport"]["runtime_ingest_performed"] is False
    assert energy_build_payload["mutation"]["safety_api_called"] is False
    assert energy_build_payload["boundary"]["medical_diagnosis"] is False
    assert energy_build_payload["boundary"]["phase1_runtime_safety_truth"] is False
    assert "secret-token-value" not in energy_build_serialized
    assert "garmin.account.private" not in energy_build_serialized
    assert "garmin.watch.private" not in energy_build_serialized
    assert "heartRateSamples" not in energy_build_serialized
    assert "geoPolylineDTO" not in energy_build_serialized
    assert "/safety/" not in energy_build_serialized


def test_admin_provider_live_output_dir_is_anchored_to_wearable_inventory(tmp_path, monkeypatch):
    data_root = tmp_path / "data"
    monkeypatch.setenv("SCOUT_DATA_ROOT", str(data_root))
    client = TestClient(create_admin_app())

    blocked = client.post(
        "/admin/wearables/provider-live-credential-vault-reference",
        json={
            "provider": "apple_healthkit_live",
            "vault_ref": "vault.ref",
            "account_ref": "account.ref",
            "token_ref": "token.ref",
            "scopes": ["workout:read", "heart_rate:read"],
            "capabilities": ["activity_summary_import", "heart_rate_samples"],
            "explicit_consent": True,
            "output_dir": str(tmp_path / "outside"),
        },
    )
    assert blocked.status_code == 422

    accepted = client.post(
        "/admin/wearables/provider-live-credential-vault-reference",
        json={
            "provider": "apple_healthkit_live",
            "vault_ref": "vault.ref",
            "account_ref": "account.ref",
            "token_ref": "token.ref",
            "scopes": ["workout:read", "heart_rate:read"],
            "capabilities": ["activity_summary_import", "heart_rate_samples"],
            "explicit_consent": True,
            "output_dir": "operator-reviewed",
        },
    )

    assert accepted.status_code == 200
    output_path = Path(accepted.json()["credential_vault_reference_path"]).resolve()
    expected_root = (
        data_root / "admin" / "wearables" / "outputs" / "operator-reviewed"
    ).resolve()
    assert output_path.parent == expected_root


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


def _write_garmin_health_api_response_fixture(path: Path) -> Path:
    payload = {
        "activities": [
            {
                "activityId": 987654321,
                "startTimeGMT": "2026-05-26T00:00:00Z",
                "duration": 3600,
                "movingDuration": 3400,
                "distance": 4100,
                "elevationGain": 180,
                "elevationLoss": 175,
                "heartRateSamples": [
                    {"timeOffsetSeconds": 0, "heartRate": 105},
                    {"timeOffsetSeconds": 1800, "heartRate": 128},
                    {"timeOffsetSeconds": 3400, "heartRate": 119},
                ],
                "bodyBattery": {"start": 72, "end": 51},
                "stress": {"avg": 42},
                "geoPolylineDTO": {"polyline": "private-route-one"},
            },
            {
                "activityId": 987654322,
                "startTimeGMT": "2026-05-27T00:00:00Z",
                "duration": 5400,
                "movingDuration": 5000,
                "distance": 5600,
                "elevationGain": 320,
                "elevationLoss": 315,
                "heartRateSamples": [
                    {"timeOffsetSeconds": 0, "heartRate": 98},
                    {"timeOffsetSeconds": 1400, "heartRate": 126},
                    {"timeOffsetSeconds": 3200, "heartRate": 142},
                    {"timeOffsetSeconds": 5000, "heartRate": 119},
                ],
                "bodyBattery": {"start": 68, "end": 38},
                "stress": {"avg": 59},
                "geoPolylineDTO": {"polyline": "private-route-two"},
            },
        ]
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


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
