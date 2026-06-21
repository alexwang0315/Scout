from scout_gee_integration import (
    build_gee_runtime_status,
    fetch_gee_environment_evidence,
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


def test_gee_fetch_uses_injected_client_without_live_network() -> None:
    class FakeGeeClient:
        def fetch_environment_summary(self, **kwargs):
            assert kwargs["project_id"] == "test-project"
            assert kwargs["bbox_wgs84"]["west"] == 121.1
            return {
                "responses": {
                    "smap_l4_surface_rootzone_soil_moisture": {
                        "http_status": 200,
                        "result": {
                            "sm_surface": 0.34,
                            "sm_rootzone": 0.41,
                        },
                    },
                    "gpm_imerg_precipitation": {
                        "http_status": 200,
                        "result": {"precipitation": 18.5},
                    },
                },
                "secret_value_embedded": False,
            }

    result = fetch_gee_environment_evidence(
        project_id="test-project",
        bbox_wgs84={"west": 121.1, "south": 23.8, "east": 121.2, "north": 23.9},
        prepared_at="2026-05-22T00:00:00+00:00",
        env={
            "SCOUT_GEE_ENABLED": "true",
            "SCOUT_GEE_PROJECT_ID": "test-project",
            "EARTHENGINE_TOKEN": "test-token-ref",
        },
        client=FakeGeeClient(),
    )

    assert result.status == "fetched"
    assert result.external_api_calls_made is True
    assert result.smap_summary["sm_surface_wetness"] == 0.34
    assert result.smap_summary["sm_rootzone_wetness"] == 0.41
    assert result.gpm_summary["last_72h_mm"] == 18.5
    assert result.raw_summary["secret_value_embedded"] is False
    payload = result.to_dict()
    assert payload["runtime_safety_truth"] is False
    assert payload["cache_policy"]["cacheable"] is False
    assert payload["cache_policy"]["ttl_seconds"] == 0
    assert payload["cache_policy"]["must_refetch_on_prepare"] is True
    assert result.raw_summary["cache_policy"]["cacheable"] is False
    assert result.smap_summary["cache_policy"]["cacheable"] is False
    assert result.gpm_timeseries["cache_policy"]["reuse_previous_numeric_values"] is False
