import json

from scout_gee_integration import (
    build_environment_risk_derivatives,
    build_route_segments_from_gpx,
    build_scout_gee_feature_package,
    build_gee_runtime_status,
    fetch_gee_environment_evidence,
    gee_environment_dataset_catalog,
    gee_route_feature_dataset_catalog,
    load_gee_dataset_config,
    write_environment_risk_derivative_artifacts,
    write_scout_gee_feature_package,
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


def test_gee_route_dataset_config_lists_v0_1_datasets() -> None:
    config = load_gee_dataset_config()
    catalog = gee_route_feature_dataset_catalog()
    dataset_ids = {item["dataset_id"] for item in catalog}

    assert config["schema_version"] == "scout_gee_datasets.v0.1"
    assert {
        "NASA/NASADEM_HGT/001",
        "COPERNICUS/S2_SR_HARMONIZED",
        "GOOGLE/CLOUD_SCORE_PLUS/V1/S2_HARMONIZED",
        "COPERNICUS/S1_GRD",
        "GOOGLE/DYNAMICWORLD/V1",
        "NASA/GPM_L3/IMERG_V07",
        "UCSB-CHG/CHIRPS/DAILY",
        "FIRMS",
    }.issubset(dataset_ids)
    assert all(item["server_side_only"] is True for item in catalog)
    assert all(item["runtime_safety_truth"] is False for item in catalog)


def test_gpx_route_is_split_into_fixed_distance_segments(tmp_path) -> None:
    gpx = tmp_path / "route.gpx"
    _write_test_gpx(gpx)

    points, segments = build_route_segments_from_gpx(gpx, segment_length_m=150)

    assert len(points) == 4
    assert len(segments) >= 2
    assert segments[0].segment_id == "gee.segment.0001"
    assert 145 <= segments[0].end_distance_m <= 155
    assert segments[0].midpoint.lat is not None


def test_scout_gee_feature_package_uses_fake_client_without_live_network(tmp_path) -> None:
    gpx = tmp_path / "route.gpx"
    out = tmp_path / "scout_gee_feature_package.json"
    risk = tmp_path / "route_risk.geojson"
    _write_test_gpx(gpx)
    _write_route_risk_geojson(risk)

    package = write_scout_gee_feature_package(
        gpx_path=gpx,
        output_path=out,
        project_id="test-route",
        prepared_at="2026-06-22T00:00:00Z",
        route_risk_geojson_path=risk,
        client=_FakeRouteFeatureClient(),
    )

    assert out.exists()
    assert package["schema_version"] == "scout_gee_feature_package.v0.1"
    assert package["mobile_runtime_dependency"] is False
    assert package["raspberry_pi_runtime_dependency"] is False
    assert package["boundary"]["runtime_safety_truth"] is False
    assert package["boundary"]["external_api_calls_made"] is False
    assert package["counts"]["segment_count"] >= 2
    first = package["segments"][0]
    assert first["elevation_m"] == 1500
    assert first["slope_deg"] == 32
    assert first["aspect_deg"] == 115
    assert first["terrain_ruggedness"] == 74
    assert first["curvature_proxy"] == -0.12
    assert first["flow_accumulation_proxy"] == 4500
    assert first["dynamic_world_probabilities"]["trees"] == 0.62
    assert first["sentinel2_indices"]["ndvi"] == 0.48
    assert first["sentinel2_before_after_change_score"] == 0.31
    assert first["sentinel1_before_after_backscatter_anomaly_db"] == -2.4
    assert first["gpm_recent_rainfall_mm"] == 88.5
    assert first["chirps_rainfall_anomaly"] == 1.7
    assert first["nearest_firms_active_fire_distance_m"] == 8200
    assert first["risk_fusion"]["teii_20m"] == 76
    assert "WeatherRisk" in first["risk_fusion"]
    assert "DaylightRisk" in first["risk_fusion"]
    assert "InteractionRisk" in first["risk_fusion"]
    assert {item["dataset_id"] for item in first["source_datasets"]} >= {
        "NASA/NASADEM_HGT/001",
        "GOOGLE/DYNAMICWORLD/V1",
        "NASA/GPM_L3/IMERG_V07",
    }
    assert package["raw_response_sha256"]


def test_scout_gee_feature_package_marks_stale_sentinel_layers(tmp_path) -> None:
    gpx = tmp_path / "route.gpx"
    _write_test_gpx(gpx)

    package = build_scout_gee_feature_package(
        gpx_path=gpx,
        project_id="test-route",
        prepared_at="2026-06-22T00:00:00Z",
        client=_FakeRouteFeatureClient(cloud_free_count=0),
    )

    assert package["stale_data_warnings"]
    assert package["stale_data_warnings"][0]["warning"] == "no_cloud_free_sentinel2_imagery"
    assert package["segments"][0]["confidence"]["band"] in {"low", "medium"}


def test_scout_gee_feature_package_does_not_fetch_live_by_default(tmp_path) -> None:
    gpx = tmp_path / "route.gpx"
    _write_test_gpx(gpx)

    package = build_scout_gee_feature_package(
        gpx_path=gpx,
        project_id="test-route",
        prepared_at="2026-06-22T00:00:00Z",
        env={"SCOUT_GEE_ENABLED": "true", "SCOUT_GEE_PROJECT_ID": "test-project", "EARTHENGINE_TOKEN": "token-ref"},
    )

    assert package["status"] == "not_fetched"
    assert package["boundary"]["external_api_calls_made"] is False
    assert "live_gee_fetch_not_allowed" in package["blocker_reasons"]


def test_scout_gee_feature_package_uses_route_risk_terrain_fallback(tmp_path) -> None:
    gpx = tmp_path / "route.gpx"
    risk = tmp_path / "route_risk.geojson"
    _write_test_gpx(gpx)
    _write_route_risk_geojson(risk)

    package = build_scout_gee_feature_package(
        gpx_path=gpx,
        project_id="test-route",
        prepared_at="2026-06-22T00:00:00Z",
        route_risk_geojson_path=risk,
        env={
            "SCOUT_GEE_ENABLED": "true",
            "SCOUT_GEE_PROJECT_ID": "test-project",
            "EARTHENGINE_TOKEN": "token-ref",
        },
    )

    first = package["segments"][0]
    assert first["elevation_m"] == 1550
    assert first["terrain_ruggedness"] == 88
    assert first["slope_deg"] == 36
    assert first["flow_accumulation_proxy"] == 1400
    assert first["metric_source_notes"][0]["source_kind"] == (
        "scout_risk_engine_route_profile"
    )
    assert first["runtime_safety_truth"] is False


def test_environment_risk_derivatives_create_candidate_layers(tmp_path) -> None:
    package = {
        "artifact_kind": "scout_gee_feature_package",
        "schema_version": "scout_gee_feature_package.v0.1",
        "project_id": "test-route",
        "generated_at": "2026-06-22T00:00:00Z",
        "status": "ready",
        "raw_response_sha256": "test-sha",
        "route": {
            "buffer_m": 500,
            "buffer": {
                "type": "Feature",
                "properties": {
                    "bbox_wgs84": {
                        "west": 121.17,
                        "south": 23.87,
                        "east": 121.18,
                        "north": 23.88,
                    }
                },
            },
        },
        "source_datasets": [
            {"dataset_id": "NASA/NASADEM_HGT/001", "role": "terrain"},
            {"dataset_id": "COPERNICUS/S2_SR_HARMONIZED", "role": "optical"},
            {"dataset_id": "COPERNICUS/S1_GRD", "role": "radar"},
            {"dataset_id": "GOOGLE/DYNAMICWORLD/V1", "role": "landcover"},
            {"dataset_id": "NASA/GPM_L3/IMERG_V07", "role": "rainfall"},
            {"dataset_id": "UCSB-CHG/CHIRPS/DAILY", "role": "rainfall_anomaly"},
        ],
        "segments": [
            {
                "segment_id": "gee.segment.0001",
                "index": 0,
                "start_distance_m": 0,
                "end_distance_m": 150,
                "mid_distance_m": 75,
                "center_lat": 23.87,
                "center_lon": 121.17,
                "geometry": {
                    "type": "LineString",
                    "coordinates": [[121.17, 23.87], [121.171, 23.871]],
                },
                "slope_deg": 36,
                "terrain_ruggedness": 84,
                "flow_accumulation_proxy": 6200,
                "dynamic_world_probabilities": {
                    "bare": 0.58,
                    "trees": 0.78,
                    "shrub_and_scrub": 0.16,
                },
                "sentinel2_indices": {"ndvi": 0.68, "bsi": 0.34, "ndwi": 0.22},
                "sentinel2_before_after_change_score": 0.34,
                "sentinel1_before_after_backscatter_anomaly_db": -2.8,
                "gpm_recent_rainfall_mm": 128,
                "chirps_rainfall_anomaly": 1.8,
            }
        ],
    }

    cwa_time_metadata = {
        "api_request_attempted_at_hour": "2026-06-26T01:00:00Z",
        "api_fetched_at_hour": "2026-06-26T01:00:00Z",
        "forecast_valid_until_hour": "2026-06-26T08:00:00Z",
        "valid_until_hour": "2026-06-26T09:00:00Z",
        "time_precision": "hour",
        "timezone": "UTC",
    }

    derivatives = build_environment_risk_derivatives(
        package,
        event_date="2026-06-01",
        cwa_time_metadata=cwa_time_metadata,
    )

    assert derivatives["schema_version"] == "scout_environment_risk_derivatives.v0.1"
    assert derivatives["boundary"]["runtime_safety_truth"] is False
    assert derivatives["counts"]["new_landslide_candidate_count"] == 1
    assert derivatives["counts"]["wetness_flash_flood_candidate_count"] == 1
    assert derivatives["counts"]["trail_obscurity_candidate_count"] == 1
    assert derivatives["counts"]["practical_darkness_candidate_count"] == 1
    first = derivatives["collections"]["new_landslide_candidates"]["features"][0]
    assert first["properties"]["conversion_rule_version"] == (
        "scout_new_landslide_candidate.v0.1"
    )
    assert first["properties"]["runtime_safety_truth"] is False
    wetness = derivatives["collections"]["wetness_flash_flood_susceptibility"][
        "features"
    ][0]
    assert derivatives["cwa_time_metadata"]["api_fetched_at_hour"] == (
        "2026-06-26T01:00:00Z"
    )
    assert wetness["properties"]["cwa_api_fetched_at_hour"] == (
        "2026-06-26T01:00:00Z"
    )
    assert wetness["properties"]["cwa_valid_until_hour"] == "2026-06-26T09:00:00Z"
    assert derivatives["route_revalidation_report"]["status"] == "ready"

    summary = write_environment_risk_derivative_artifacts(
        feature_package=package,
        output_dir=tmp_path,
        event_date="2026-06-01",
        cwa_time_metadata=cwa_time_metadata,
    )
    assert (tmp_path / "new_landslide_candidates.geojson").is_file()
    assert (tmp_path / "wetness_flash_flood_susceptibility.geojson").is_file()
    assert (tmp_path / "trail_obscurity_risk.geojson").is_file()
    assert (tmp_path / "practical_darkness_time.geojson").is_file()
    assert (tmp_path / "route_revalidation_report.json").is_file()
    assert summary["counts"]["segment_count"] == 1
    written_wetness = json.loads(
        (tmp_path / "wetness_flash_flood_susceptibility.geojson").read_text(
            encoding="utf-8"
        )
    )
    assert written_wetness["features"][0]["properties"][
        "cwa_api_fetched_at_hour"
    ] == "2026-06-26T01:00:00Z"


class _FakeRouteFeatureClient:
    def __init__(self, cloud_free_count: int = 3) -> None:
        self.cloud_free_count = cloud_free_count

    def fetch_route_feature_package(self, **kwargs):
        assert kwargs["project_id"] == "test-route"
        features = []
        for index, segment in enumerate(kwargs["segments"]):
            features.append(
                {
                    "segment_id": segment["properties"]["segment_id"],
                    "elevation_m": 1500 + index * 8,
                    "slope_deg": 32,
                    "aspect_deg": 115,
                    "terrain_ruggedness": 74,
                    "curvature_proxy": -0.12,
                    "terrain_position_proxy": 0.44,
                    "flow_accumulation_proxy": 4500,
                    "dynamic_world_probabilities": {
                        "water": 0.02,
                        "trees": 0.62,
                        "grass": 0.12,
                        "flooded_vegetation": 0.01,
                        "crops": 0.0,
                        "shrub_and_scrub": 0.13,
                        "built": 0.0,
                        "bare": 0.08,
                        "snow_and_ice": 0.0,
                    },
                    "sentinel2_indices": {
                        "ndvi": 0.48,
                        "bsi": 0.22,
                        "ndwi": -0.18,
                        "nbr": 0.36,
                    },
                    "sentinel2_before_after_change_score": 0.31,
                    "sentinel1_before_after_backscatter_anomaly_db": -2.4,
                    "gpm_recent_rainfall_mm": 88.5,
                    "chirps_rainfall_anomaly": 1.7,
                    "nearest_firms_active_fire_distance_m": 8200,
                    "sentinel2_cloud_free_count": self.cloud_free_count,
                    "sentinel2_status": (
                        "ready" if self.cloud_free_count else "no_cloud_free_imagery"
                    ),
                }
            )
        return {
            "provider": "google_earth_engine",
            "segment_features": features,
            "source_metadata": {},
            "stale_data_warnings": [],
            "secret_value_embedded": False,
            "external_api_call_performed": False,
            "runtime_safety_truth": False,
        }


def _write_test_gpx(path) -> None:
    path.write_text(
        """<?xml version="1.0" encoding="UTF-8"?>
<gpx version="1.1" creator="scout-test" xmlns="http://www.topografix.com/GPX/1/1">
  <trk><name>test</name><trkseg>
    <trkpt lat="23.870000" lon="121.170000"><ele>1400</ele></trkpt>
    <trkpt lat="23.871000" lon="121.171000"><ele>1420</ele></trkpt>
    <trkpt lat="23.872000" lon="121.172000"><ele>1440</ele></trkpt>
    <trkpt lat="23.873000" lon="121.173000"><ele>1460</ele></trkpt>
  </trkseg></trk>
</gpx>
""",
        encoding="utf-8",
    )


def _write_route_risk_geojson(path) -> None:
    path.write_text(
        """{
  "type": "FeatureCollection",
  "features": [
    {
      "type": "Feature",
      "geometry": {"type": "Point", "coordinates": [121.1705, 23.8705]},
      "properties": {
        "distance_m": 75,
        "elevation_m": 1550,
        "tri": 88,
        "lec": 80,
        "sri": 14,
        "teii_20m": 76,
        "WeatherRisk": 0.64,
        "DaylightRisk": "medium",
        "InteractionRisk": 0.48
      }
    }
  ]
}
""",
        encoding="utf-8",
    )
