from scout_gee_integration import (
    build_gee_runtime_status,
    gee_environment_dataset_catalog,
)


def test_gee_runtime_status_defaults_to_disabled_without_secret_values() -> None:
    status = build_gee_runtime_status({})
    payload = status.to_dict()

    assert status.enabled is False
    assert status.ready is False
    assert status.blocker_reasons == ["gee_not_enabled"]
    assert payload["provider"] == "google_earth_engine"
    assert payload["secret_value_embedded"] is False
    assert payload["external_api_call_performed"] is False


def test_gee_runtime_status_requires_project_and_credentials_when_enabled() -> None:
    status = build_gee_runtime_status({"SCOUT_GEE_ENABLED": "true"})

    assert status.ready is False
    assert "missing_gee_project_ref" in status.blocker_reasons
    assert "missing_gee_credentials_ref:adc" in status.blocker_reasons


def test_gee_runtime_status_accepts_service_account_refs_without_values() -> None:
    status = build_gee_runtime_status(
        {
            "SCOUT_GEE_ENABLED": "true",
            "SCOUT_GEE_PROJECT_ID": "test-project",
            "SCOUT_GEE_AUTH_MODE": "service_account",
            "SCOUT_GEE_SERVICE_ACCOUNT": "service-account@example.invalid",
            "SCOUT_GEE_CREDENTIALS_PATH": "/server/secret/earthengine.json",
        }
    )
    payload = status.to_dict()

    assert status.ready is True
    assert status.project_id_ref == "env:SCOUT_GEE_PROJECT_ID"
    assert status.account_ref == "env:SCOUT_GEE_SERVICE_ACCOUNT"
    assert payload["credential_refs"] == ["env:SCOUT_GEE_CREDENTIALS_PATH"]
    assert payload["secret_value_embedded"] is False


def test_gee_dataset_catalog_is_candidate_only_environment_evidence() -> None:
    catalog = gee_environment_dataset_catalog()
    collection_ids = {dataset["collection_id"] for dataset in catalog}

    assert "NASA/SMAP/SPL3SMP_E/006" in collection_ids
    assert "NASA/SMAP/SPL4SMGP/008" in collection_ids
    assert "NASA/GPM_L3/IMERG_V07" in collection_ids
    assert all(dataset["runtime_safety_truth"] is False for dataset in catalog)
