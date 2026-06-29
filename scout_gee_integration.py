from __future__ import annotations

import json
import hashlib
import math
import os
import xml.etree.ElementTree as ET
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


GEE_PROVIDER_ID = "google_earth_engine"
SCOUT_GEE_ENABLED_ENV = "SCOUT_GEE_ENABLED"
SCOUT_GEE_PROJECT_ID_ENV = "SCOUT_GEE_PROJECT_ID"
LEGACY_SCOUT_GEE_PROJECT_ENV = "SCOUT_GEE_PROJECT"
GOOGLE_CLOUD_PROJECT_ENV = "GOOGLE_CLOUD_PROJECT"
SCOUT_GEE_AUTH_MODE_ENV = "SCOUT_GEE_AUTH_MODE"
SCOUT_GEE_CREDENTIALS_PATH_ENV = "SCOUT_GEE_CREDENTIALS_PATH"
SCOUT_GEE_SERVICE_ACCOUNT_ENV = "SCOUT_GEE_SERVICE_ACCOUNT"
SCOUT_GEE_ACCOUNT_ENV = "SCOUT_GEE_ACCOUNT"
GOOGLE_APPLICATION_CREDENTIALS_ENV = "GOOGLE_APPLICATION_CREDENTIALS"
EARTHENGINE_TOKEN_ENV = "EARTHENGINE_TOKEN"
SCOUT_GEE_OAUTH_CLIENT_ID_ENV = "SCOUT_GEE_OAUTH_CLIENT_ID"
SCOUT_GEE_OAUTH_CLIENT_SECRET_ENV = "SCOUT_GEE_OAUTH_CLIENT_SECRET"
GEE_VALUE_COMPUTE_URL_TEMPLATE = (
    "https://earthengine.googleapis.com/v1/projects/{project_id}/value:compute"
)
GEE_OAUTH_TOKEN_URL = "https://oauth2.googleapis.com/token"
SCOUT_GEE_FEATURE_PACKAGE_VERSION = "scout_gee_feature_package.v0.1"
SCOUT_ENVIRONMENT_RISK_DERIVATIVE_VERSION = "scout_environment_risk_derivatives.v0.1"
DEFAULT_GEE_ROUTE_SEGMENT_LENGTH_M = 150.0
MIN_GEE_ROUTE_SEGMENT_LENGTH_M = 100.0
MAX_GEE_ROUTE_SEGMENT_LENGTH_M = 250.0
DEFAULT_GEE_ROUTE_BUFFER_M = 60.0
DEFAULT_GEE_DATASET_CONFIG_PATH = (
    Path(__file__).resolve().parent / "config" / "gee_datasets.yaml"
)

SUPPORTED_GEE_AUTH_MODES = {
    "adc",
    "service_account",
    "user",
    "user_oauth",
}

GEE_ENVIRONMENT_DATASETS: tuple[dict[str, Any], ...] = (
    {
        "dataset_key": "smap_l3_surface_soil_moisture",
        "collection_id": "NASA/SMAP/SPL3SMP_E/006",
        "label": "SMAP L3 surface soil moisture",
        "label_zh": "SMAP L3 地表土壤含水量",
        "scout_use": "surface wetness background and anomaly review",
        "runtime_safety_truth": False,
    },
    {
        "dataset_key": "smap_l4_surface_rootzone_soil_moisture",
        "collection_id": "NASA/SMAP/SPL4SMGP/008",
        "label": "SMAP L4 surface and root-zone soil moisture",
        "label_zh": "SMAP L4 表層與根系層土壤含水量",
        "scout_use": "antecedent wetness trend and route-corridor hydrology review",
        "runtime_safety_truth": False,
    },
    {
        "dataset_key": "gpm_imerg_precipitation",
        "collection_id": "NASA/GPM_L3/IMERG_V07",
        "label": "GPM IMERG precipitation",
        "label_zh": "GPM IMERG 衛星/模式降雨估計",
        "scout_use": "antecedent rainfall accumulation and compound wetness review",
        "runtime_safety_truth": False,
    },
)

GEE_NUMERIC_NO_CACHE_POLICY: dict[str, Any] = {
    "cacheable": False,
    "ttl_seconds": 0,
    "must_refetch_on_prepare": True,
    "reuse_previous_numeric_values": False,
    "artifact_role": "current_run_evidence_snapshot",
    "reason": (
        "GEE SMAP/GPM environment values are time-sensitive and must be "
        "refetched during every explicit map preparation run."
    ),
}

DEFAULT_ROUTE_FEATURE_DATASET_CONFIG: dict[str, Any] = {
    "schema_version": "scout_gee_datasets.v0.1",
    "package_version": SCOUT_GEE_FEATURE_PACKAGE_VERSION,
    "cloud_filtering": {
        "sentinel2_cloud_score_plus_min_cs": 0.60,
        "sentinel2_cloud_score_plus_min_cs_cdf": 0.50,
        "sentinel2_max_cloud_probability": 35,
        "stale_days_without_cloud_free_imagery": 45,
    },
    "datasets": [
        {
            "key": "nasadem",
            "dataset_id": "NASA/NASADEM_HGT/001",
            "role": "terrain",
            "bands": ["elevation"],
            "date_range": "static",
            "confidence": 0.82,
        },
        {
            "key": "sentinel2_sr",
            "dataset_id": "COPERNICUS/S2_SR_HARMONIZED",
            "role": "optical_indices",
            "bands": ["B2", "B3", "B4", "B8", "B11", "B12", "SCL"],
            "date_range": "recent_90d",
            "confidence": 0.72,
        },
        {
            "key": "cloud_score_plus",
            "dataset_id": "GOOGLE/CLOUD_SCORE_PLUS/V1/S2_HARMONIZED",
            "role": "sentinel2_cloud_filter",
            "bands": ["cs", "cs_cdf"],
            "date_range": "recent_90d",
            "confidence": 0.75,
        },
        {
            "key": "sentinel1_grd",
            "dataset_id": "COPERNICUS/S1_GRD",
            "role": "radar_backscatter_change",
            "bands": ["VV", "VH"],
            "date_range": "before_after_180d",
            "confidence": 0.70,
        },
        {
            "key": "dynamic_world",
            "dataset_id": "GOOGLE/DYNAMICWORLD/V1",
            "role": "landcover_probabilities",
            "bands": [
                "water",
                "trees",
                "grass",
                "flooded_vegetation",
                "crops",
                "shrub_and_scrub",
                "built",
                "bare",
                "snow_and_ice",
                "label",
            ],
            "date_range": "recent_365d",
            "confidence": 0.68,
        },
        {
            "key": "gpm_imerg",
            "dataset_id": "NASA/GPM_L3/IMERG_V07",
            "role": "recent_rainfall",
            "bands": ["precipitation"],
            "date_range": "recent_72h",
            "confidence": 0.72,
        },
        {
            "key": "chirps_daily",
            "dataset_id": "UCSB-CHG/CHIRPS/DAILY",
            "role": "rainfall_anomaly",
            "bands": ["precipitation"],
            "date_range": "recent_30d_vs_climatology",
            "confidence": 0.70,
        },
        {
            "key": "firms",
            "dataset_id": "FIRMS",
            "role": "active_fire_distance",
            "bands": ["T21", "confidence"],
            "date_range": "recent_7d",
            "confidence": 0.62,
        },
    ],
}


@dataclass(frozen=True)
class GeeRuntimeStatus:
    enabled: bool
    ready: bool
    project_id_ref: str | None
    auth_mode: str | None
    credential_refs: list[str]
    account_ref: str | None
    blocker_reasons: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": GEE_PROVIDER_ID,
            "enabled": self.enabled,
            "ready": self.ready,
            "project_id_ref": self.project_id_ref,
            "auth_mode": self.auth_mode,
            "credential_refs": list(self.credential_refs),
            "account_ref": self.account_ref,
            "blocker_reasons": list(self.blocker_reasons),
            "secret_value_embedded": False,
            "external_api_call_performed": False,
            "runtime_safety_truth": False,
        }


@dataclass(frozen=True)
class GeeFetchWindow:
    start: str
    end: str


@dataclass(frozen=True)
class GeeFetchResult:
    status: str
    blocker_reasons: list[str]
    external_api_calls_made: bool
    raw_summary: dict[str, Any]
    smap_summary: dict[str, Any]
    gpm_summary: dict[str, Any]
    smap_timeseries: dict[str, Any]
    gpm_timeseries: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "blocker_reasons": list(self.blocker_reasons),
            "external_api_calls_made": self.external_api_calls_made,
            "cache_policy": gee_numeric_no_cache_policy(),
            "raw_summary": self.raw_summary,
            "soil_moisture": self.smap_summary,
            "antecedent_rain": self.gpm_summary,
            "smap_timeseries": self.smap_timeseries,
            "gpm_timeseries": self.gpm_timeseries,
            "secret_value_embedded": False,
            "runtime_safety_truth": False,
        }


@dataclass(frozen=True)
class GeeRoutePoint:
    lat: float
    lon: float
    elevation_m: float | None
    distance_m: float
    timestamp: str | None = None


@dataclass(frozen=True)
class GeeRouteSegment:
    segment_id: str
    index: int
    start_distance_m: float
    end_distance_m: float
    mid_distance_m: float
    start: GeeRoutePoint
    end: GeeRoutePoint
    midpoint: GeeRoutePoint

    def to_feature(self) -> dict[str, Any]:
        return {
            "type": "Feature",
            "geometry": {
                "type": "LineString",
                "coordinates": [
                    [self.start.lon, self.start.lat],
                    [self.end.lon, self.end.lat],
                ],
            },
            "properties": {
                "segment_id": self.segment_id,
                "index": self.index,
                "start_distance_m": round(self.start_distance_m, 2),
                "end_distance_m": round(self.end_distance_m, 2),
                "mid_distance_m": round(self.mid_distance_m, 2),
                "center_lat": self.midpoint.lat,
                "center_lon": self.midpoint.lon,
            },
        }


class GeeFetchError(RuntimeError):
    def __init__(self, blocker_reasons: list[str], raw_summary: dict[str, Any] | None = None):
        super().__init__(", ".join(blocker_reasons))
        self.blocker_reasons = blocker_reasons
        self.raw_summary = raw_summary or {}


class RestGeeEnvironmentClient:
    """Minimal Earth Engine REST client for route-corridor environment summaries."""

    def __init__(self, env: Mapping[str, str] | None = None, *, timeout_s: int = 45):
        self._env = os.environ if env is None else env
        self._timeout_s = timeout_s

    def fetch_environment_summary(
        self,
        *,
        project_id: str,
        bbox_wgs84: Mapping[str, float],
        prepared_at: str,
        smap_window: GeeFetchWindow,
        gpm_window: GeeFetchWindow,
    ) -> dict[str, Any]:
        token = _gee_access_token(self._env)
        requests: list[dict[str, Any]] = []
        smap = self._compute_value(
            project_id=project_id,
            token=token,
            expression=_smap_l4_mean_expression(bbox_wgs84, smap_window),
        )
        requests.append(
            _raw_request_record(
                dataset_key="smap_l4_surface_rootzone_soil_moisture",
                collection_id="NASA/SMAP/SPL4SMGP/008",
                window=smap_window,
            )
        )
        gpm = self._compute_value(
            project_id=project_id,
            token=token,
            expression=_gpm_imerg_sum_expression(bbox_wgs84, gpm_window),
        )
        requests.append(
            _raw_request_record(
                dataset_key="gpm_imerg_precipitation",
                collection_id="NASA/GPM_L3/IMERG_V07",
                window=gpm_window,
            )
        )
        return {
            "provider": GEE_PROVIDER_ID,
            "project_id_ref": "env:SCOUT_GEE_PROJECT_ID",
            "prepared_at": prepared_at,
            "bbox_wgs84": dict(bbox_wgs84),
            "cache_policy": gee_numeric_no_cache_policy(),
            "requests": requests,
            "responses": {
                "smap_l4_surface_rootzone_soil_moisture": smap,
                "gpm_imerg_precipitation": gpm,
            },
            "secret_value_embedded": False,
            "external_api_call_performed": True,
            "runtime_safety_truth": False,
        }

    def _compute_value(
        self,
        *,
        project_id: str,
        token: str,
        expression: dict[str, Any],
    ) -> dict[str, Any]:
        url = GEE_VALUE_COMPUTE_URL_TEMPLATE.format(
            project_id=urllib.parse.quote(project_id, safe="")
        )
        body = json_dumps_bytes({"expression": expression})
        request = urllib.request.Request(
            url,
            data=body,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self._timeout_s) as response:
                payload = _json_loads_bytes(response.read())
                return {
                    "http_status": response.status,
                    "result": payload.get("result"),
                    "error": None,
                }
        except urllib.error.HTTPError as exc:
            error_payload = _safe_error_payload(exc)
            raise GeeFetchError(
                [f"gee_http_error:{exc.code}"],
                raw_summary={"http_status": exc.code, "error": error_payload},
            ) from exc
        except urllib.error.URLError as exc:
            raise GeeFetchError(
                [f"gee_network_error:{type(exc.reason).__name__}"],
                raw_summary={"error": str(exc.reason), "secret_value_embedded": False},
            ) from exc


class RestGeeRouteFeatureClient:
    """Server-side Earth Engine REST runner for compact route feature packages."""

    def __init__(self, env: Mapping[str, str] | None = None, *, timeout_s: int = 90):
        self._env = os.environ if env is None else env
        self._timeout_s = timeout_s

    def fetch_route_feature_package(
        self,
        *,
        project_id: str,
        route_polyline: dict[str, Any],
        route_buffer: dict[str, Any],
        segments: list[dict[str, Any]],
        dataset_config: Mapping[str, Any],
        date_ranges: Mapping[str, Any],
        prepared_at: str,
    ) -> dict[str, Any]:
        token = _gee_access_token(self._env)
        expression = _route_feature_job_expression(
            route_polyline=route_polyline,
            route_buffer=route_buffer,
            segments=segments,
            dataset_config=dataset_config,
            date_ranges=date_ranges,
            prepared_at=prepared_at,
        )
        response = self._compute_value(
            project_id=project_id,
            token=token,
            expression=expression,
        )
        result = response.get("result")
        if isinstance(result, Mapping):
            payload = dict(result)
        else:
            payload = {}
        return {
            "provider": GEE_PROVIDER_ID,
            "project_id_ref": "env:SCOUT_GEE_PROJECT_ID",
            "prepared_at": prepared_at,
            "endpoint": GEE_VALUE_COMPUTE_URL_TEMPLATE,
            "http_status": response.get("http_status"),
            "compiled_job": expression,
            "result": payload,
            "segment_features": payload.get("segment_features", []),
            "source_metadata": payload.get("source_metadata", {}),
            "stale_data_warnings": payload.get("stale_data_warnings", []),
            "secret_value_embedded": False,
            "external_api_call_performed": True,
            "runtime_safety_truth": False,
        }

    def _compute_value(
        self,
        *,
        project_id: str,
        token: str,
        expression: dict[str, Any],
    ) -> dict[str, Any]:
        url = GEE_VALUE_COMPUTE_URL_TEMPLATE.format(
            project_id=urllib.parse.quote(project_id, safe="")
        )
        body = json_dumps_bytes({"expression": expression})
        request = urllib.request.Request(
            url,
            data=body,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self._timeout_s) as response:
                payload = _json_loads_bytes(response.read())
                return {
                    "http_status": response.status,
                    "result": payload.get("result"),
                    "error": None,
                }
        except urllib.error.HTTPError as exc:
            raise GeeFetchError(
                [f"gee_route_feature_http_error:{exc.code}"],
                raw_summary={"http_status": exc.code, "error": _safe_error_payload(exc)},
            ) from exc
        except urllib.error.URLError as exc:
            raise GeeFetchError(
                [f"gee_route_feature_network_error:{type(exc.reason).__name__}"],
                raw_summary={"error": str(exc.reason), "secret_value_embedded": False},
            ) from exc


def build_gee_runtime_status(env: Mapping[str, str] | None = None) -> GeeRuntimeStatus:
    active_env = os.environ if env is None else env
    enabled = _truthy(active_env.get(SCOUT_GEE_ENABLED_ENV))
    project_id_ref = _first_present_env_ref(
        active_env,
        SCOUT_GEE_PROJECT_ID_ENV,
        LEGACY_SCOUT_GEE_PROJECT_ENV,
        GOOGLE_CLOUD_PROJECT_ENV,
    )
    auth_mode = str(active_env.get(SCOUT_GEE_AUTH_MODE_ENV, "adc")).strip().lower() or "adc"
    credential_refs = _gee_credential_refs(active_env, auth_mode)
    account_ref = _first_present_env_ref(
        active_env,
        SCOUT_GEE_SERVICE_ACCOUNT_ENV,
        SCOUT_GEE_ACCOUNT_ENV,
    )

    blockers: list[str] = []
    if not enabled:
        blockers.append("gee_not_enabled")
    if enabled and not project_id_ref:
        blockers.append("missing_gee_project_ref")
    if enabled and auth_mode not in SUPPORTED_GEE_AUTH_MODES:
        blockers.append(f"unsupported_gee_auth_mode:{auth_mode}")
    if enabled and not credential_refs:
        blockers.append(f"missing_gee_credentials_ref:{auth_mode}")
    if enabled and auth_mode == "service_account" and not account_ref:
        blockers.append("missing_gee_service_account_ref")

    return GeeRuntimeStatus(
        enabled=enabled,
        ready=enabled and not blockers,
        project_id_ref=project_id_ref,
        auth_mode=auth_mode,
        credential_refs=credential_refs,
        account_ref=account_ref,
        blocker_reasons=blockers,
    )


def gee_environment_dataset_catalog() -> list[dict[str, Any]]:
    return [dict(dataset) for dataset in GEE_ENVIRONMENT_DATASETS]


def gee_numeric_no_cache_policy() -> dict[str, Any]:
    return dict(GEE_NUMERIC_NO_CACHE_POLICY)


def default_gee_fetch_windows(prepared_at: str) -> dict[str, GeeFetchWindow]:
    end = _parse_datetime(prepared_at)
    return {
        "smap_l4": GeeFetchWindow(
            start=(end - timedelta(days=30)).date().isoformat(),
            end=end.date().isoformat(),
        ),
        "gpm_imerg": GeeFetchWindow(
            start=(end - timedelta(hours=72)).isoformat().replace("+00:00", "Z"),
            end=end.isoformat().replace("+00:00", "Z"),
        ),
    }


def fetch_gee_environment_evidence(
    *,
    project_id: str,
    bbox_wgs84: Mapping[str, float],
    prepared_at: str,
    env: Mapping[str, str] | None = None,
    client: Any | None = None,
) -> GeeFetchResult:
    active_env = os.environ if env is None else env
    status = build_gee_runtime_status(active_env)
    if not status.ready:
        return _blocked_fetch_result(
            status="missing_credentials",
            blockers=status.blocker_reasons,
            project_id=project_id,
            bbox_wgs84=bbox_wgs84,
            prepared_at=prepared_at,
        )

    windows = default_gee_fetch_windows(prepared_at)
    fetch_client = client or RestGeeEnvironmentClient(active_env)
    try:
        raw_summary = fetch_client.fetch_environment_summary(
            project_id=project_id,
            bbox_wgs84=bbox_wgs84,
            prepared_at=prepared_at,
            smap_window=windows["smap_l4"],
            gpm_window=windows["gpm_imerg"],
        )
    except GeeFetchError as exc:
        return _blocked_fetch_result(
            status="fetch_failed",
            blockers=exc.blocker_reasons,
            project_id=project_id,
            bbox_wgs84=bbox_wgs84,
            prepared_at=prepared_at,
            raw_summary=exc.raw_summary,
            external_api_calls_made=True,
        )
    except Exception as exc:  # pragma: no cover - defensive adapter boundary.
        return _blocked_fetch_result(
            status="fetch_failed",
            blockers=[f"gee_fetch_failed:{type(exc).__name__}"],
            project_id=project_id,
            bbox_wgs84=bbox_wgs84,
            prepared_at=prepared_at,
            raw_summary={"error_type": type(exc).__name__, "secret_value_embedded": False},
            external_api_calls_made=True,
        )

    return normalize_gee_environment_summary(
        raw_summary,
        project_id=project_id,
        bbox_wgs84=bbox_wgs84,
        prepared_at=prepared_at,
        external_api_calls_made=True,
    )


def normalize_gee_environment_summary(
    raw_summary: Mapping[str, Any],
    *,
    project_id: str,
    bbox_wgs84: Mapping[str, float],
    prepared_at: str,
    external_api_calls_made: bool,
) -> GeeFetchResult:
    cache_policy = gee_numeric_no_cache_policy()
    responses = raw_summary.get("responses") if isinstance(raw_summary, Mapping) else {}
    responses = responses if isinstance(responses, Mapping) else {}
    smap_result = _mapping_result(
        responses.get("smap_l4_surface_rootzone_soil_moisture")
    )
    gpm_result = _mapping_result(responses.get("gpm_imerg_precipitation"))
    sm_surface = _first_number(
        smap_result,
        "sm_surface",
        "sm_surface_mean",
        "smap_l4_surface",
        "surface",
    )
    sm_rootzone = _first_number(
        smap_result,
        "sm_rootzone",
        "sm_rootzone_mean",
        "smap_l4_rootzone",
        "rootzone",
    )
    gpm_precip = _first_number(
        gpm_result,
        "precipitation",
        "precipitation_sum",
        "gpm_imerg_precipitation",
        "rainfall_mm",
    )
    status = "fetched" if any(
        value is not None for value in (sm_surface, sm_rootzone, gpm_precip)
    ) else "fetched_empty"
    blockers = [] if status == "fetched" else ["gee_response_empty_or_unrecognized"]
    smap_sample = {
        "timestamp": prepared_at,
        "sm_surface": sm_surface,
        "sm_rootzone": sm_rootzone,
        "sample_kind": "corridor_period_mean",
    }
    gpm_sample = {
        "timestamp": prepared_at,
        "last_72h_mm": gpm_precip,
        "sample_kind": "corridor_period_sum_mean",
    }
    return GeeFetchResult(
        status=status,
        blocker_reasons=blockers,
        external_api_calls_made=external_api_calls_made,
        raw_summary={
            **dict(raw_summary),
            "project_id": project_id,
            "bbox_wgs84": dict(bbox_wgs84),
            "prepared_at": prepared_at,
            "cache_policy": cache_policy,
            "secret_value_embedded": False,
            "runtime_safety_truth": False,
        },
        smap_summary={
            "dataset_family": "SMAP",
            "collection_id": "NASA/SMAP/SPL4SMGP/008",
            "status": status,
            "sm_surface_wetness": sm_surface,
            "sm_rootzone_wetness": sm_rootzone,
            "antecedent_wetness_percentile": None,
            "aggregation": "bbox_reduce_region_mean",
            "sample_count": 1 if sm_surface is not None or sm_rootzone is not None else 0,
            "samples": [smap_sample],
            "cache_policy": cache_policy,
        },
        gpm_summary={
            "dataset_family": "GPM_IMERG",
            "collection_id": "NASA/GPM_L3/IMERG_V07",
            "status": status,
            "last_72h_mm": gpm_precip,
            "last_24h_mm": None,
            "last_3h_mm": None,
            "aggregation": "image_collection_sum_then_bbox_mean",
            "sample_count": 1 if gpm_precip is not None else 0,
            "samples": [gpm_sample],
            "cache_policy": cache_policy,
        },
        smap_timeseries={
            "artifact_kind": "gee_soil_moisture_timeseries",
            "project_id": project_id,
            "layer_id": "soil-moisture",
            "generated_at": prepared_at,
            "status": status,
            "samples": [smap_sample],
            "cache_policy": cache_policy,
            "candidate_only": True,
            "runtime_safety_truth": False,
        },
        gpm_timeseries={
            "artifact_kind": "gee_antecedent_rain_timeseries",
            "project_id": project_id,
            "layer_id": "antecedent-rain",
            "generated_at": prepared_at,
            "status": status,
            "samples": [gpm_sample],
            "cache_policy": cache_policy,
            "candidate_only": True,
            "runtime_safety_truth": False,
        },
    )


def load_gee_dataset_config(path: str | Path | None = None) -> dict[str, Any]:
    config_path = Path(path) if path is not None else DEFAULT_GEE_DATASET_CONFIG_PATH
    if not config_path.exists():
        return json.loads(json.dumps(DEFAULT_ROUTE_FEATURE_DATASET_CONFIG))
    raw = config_path.read_text(encoding="utf-8")
    try:
        loaded = json.loads(raw)
    except json.JSONDecodeError:
        try:
            import yaml

            loaded = yaml.safe_load(raw)
        except Exception:
            loaded = json.loads(json.dumps(DEFAULT_ROUTE_FEATURE_DATASET_CONFIG))
    if not isinstance(loaded, Mapping):
        raise ValueError("GEE dataset config must be a mapping")
    config = dict(loaded)
    datasets = config.get("datasets")
    if not isinstance(datasets, list):
        raise ValueError("GEE dataset config requires a datasets list")
    required_ids = {
        "NASA/NASADEM_HGT/001",
        "COPERNICUS/S2_SR_HARMONIZED",
        "GOOGLE/CLOUD_SCORE_PLUS/V1/S2_HARMONIZED",
        "COPERNICUS/S1_GRD",
        "GOOGLE/DYNAMICWORLD/V1",
        "NASA/GPM_L3/IMERG_V07",
        "UCSB-CHG/CHIRPS/DAILY",
        "FIRMS",
    }
    found_ids = {
        str(dataset.get("dataset_id"))
        for dataset in datasets
        if isinstance(dataset, Mapping)
    }
    missing = sorted(required_ids - found_ids)
    if missing:
        raise ValueError(f"GEE dataset config missing datasets: {', '.join(missing)}")
    config.setdefault("cloud_filtering", {})
    config.setdefault("schema_version", "scout_gee_datasets.v0.1")
    return config


def gee_route_feature_dataset_catalog(path: str | Path | None = None) -> list[dict[str, Any]]:
    config = load_gee_dataset_config(path)
    return [
        {
            **dict(dataset),
            "runtime_safety_truth": False,
            "server_side_only": True,
        }
        for dataset in config.get("datasets", [])
        if isinstance(dataset, Mapping)
    ]


def build_route_segments_from_gpx(
    gpx_path: str | Path,
    *,
    segment_length_m: float = DEFAULT_GEE_ROUTE_SEGMENT_LENGTH_M,
) -> tuple[list[GeeRoutePoint], list[GeeRouteSegment]]:
    _validate_route_segment_length(segment_length_m)
    points = _load_gpx_route_points(Path(gpx_path))
    if len(points) < 2:
        raise ValueError("GPX route must contain at least two route points")
    total_distance = points[-1].distance_m
    if total_distance <= 0:
        raise ValueError("GPX route distance must be greater than zero")
    distances = [0.0]
    cursor = segment_length_m
    while cursor < total_distance:
        distances.append(cursor)
        cursor += segment_length_m
    if distances[-1] < total_distance:
        distances.append(total_distance)
    samples = [_interpolate_route_point(points, distance) for distance in distances]
    segments: list[GeeRouteSegment] = []
    for index, (start, end) in enumerate(zip(samples, samples[1:])):
        mid_distance = (start.distance_m + end.distance_m) / 2
        midpoint = _interpolate_route_point(points, mid_distance)
        segments.append(
            GeeRouteSegment(
                segment_id=f"gee.segment.{index + 1:04d}",
                index=index,
                start_distance_m=start.distance_m,
                end_distance_m=end.distance_m,
                mid_distance_m=mid_distance,
                start=start,
                end=end,
                midpoint=midpoint,
            )
        )
    return points, segments


def build_scout_gee_feature_package(
    *,
    gpx_path: str | Path,
    project_id: str,
    prepared_at: str,
    segment_length_m: float = DEFAULT_GEE_ROUTE_SEGMENT_LENGTH_M,
    buffer_m: float = DEFAULT_GEE_ROUTE_BUFFER_M,
    dataset_config_path: str | Path | None = None,
    route_risk_geojson_path: str | Path | None = None,
    env: Mapping[str, str] | None = None,
    client: Any | None = None,
    allow_live_fetch: bool = False,
) -> dict[str, Any]:
    active_env = os.environ if env is None else env
    dataset_config = load_gee_dataset_config(dataset_config_path)
    route_points, route_segments = build_route_segments_from_gpx(
        gpx_path,
        segment_length_m=segment_length_m,
    )
    route_polyline = _route_polyline_feature(route_points)
    route_buffer = _route_buffer_feature(route_points, buffer_m=buffer_m)
    segment_features = [segment.to_feature() for segment in route_segments]
    bbox = route_buffer["properties"]["bbox_wgs84"]
    date_ranges = _route_feature_date_ranges(dataset_config, prepared_at)
    status = build_gee_runtime_status(active_env)
    external_api_calls_made = False
    blockers: list[str] = []

    raw_summary: dict[str, Any]
    if client is not None:
        raw_summary = client.fetch_route_feature_package(
            project_id=project_id,
            route_polyline=route_polyline,
            route_buffer=route_buffer,
            segments=segment_features,
            dataset_config=dataset_config,
            date_ranges=date_ranges,
            prepared_at=prepared_at,
        )
        external_api_calls_made = bool(raw_summary.get("external_api_call_performed"))
    elif allow_live_fetch and status.ready:
        try:
            raw_summary = RestGeeRouteFeatureClient(active_env).fetch_route_feature_package(
                project_id=project_id,
                route_polyline=route_polyline,
                route_buffer=route_buffer,
                segments=segment_features,
                dataset_config=dataset_config,
                date_ranges=date_ranges,
                prepared_at=prepared_at,
            )
            external_api_calls_made = True
        except GeeFetchError as exc:
            blockers = list(exc.blocker_reasons)
            raw_summary = {
                "provider": GEE_PROVIDER_ID,
                "status": "fetch_failed",
                "blocker_reasons": blockers,
                "raw_error": exc.raw_summary,
                "secret_value_embedded": False,
                "external_api_call_performed": True,
                "runtime_safety_truth": False,
            }
            external_api_calls_made = True
    else:
        blockers = (
            ["live_gee_fetch_not_allowed"]
            if status.ready
            else list(status.blocker_reasons)
        )
        raw_summary = {
            "provider": GEE_PROVIDER_ID,
            "status": "not_fetched" if status.ready else "missing_credentials",
            "blocker_reasons": blockers,
            "secret_value_embedded": False,
            "external_api_call_performed": False,
            "runtime_safety_truth": False,
        }

    risk_samples = _load_route_risk_samples(route_risk_geojson_path)
    raw_hash = _sha256_json(raw_summary)
    normalized_segments, stale_warnings = _normalize_route_feature_segments(
        raw_summary=raw_summary,
        route_segments=route_segments,
        dataset_config=dataset_config,
        date_ranges=date_ranges,
        risk_samples=risk_samples,
    )
    raw_segment_count = len(_extract_raw_segment_features(raw_summary))
    package_status = (
        "ready"
        if raw_segment_count > 0
        else str(raw_summary.get("status") or "fetched_empty")
    )
    source_datasets = _source_dataset_records(dataset_config, date_ranges)
    confidence_summary = _package_confidence_summary(normalized_segments)
    return {
        "artifact_kind": "scout_gee_feature_package",
        "schema_version": SCOUT_GEE_FEATURE_PACKAGE_VERSION,
        "project_id": project_id,
        "generated_at": prepared_at,
        "status": package_status,
        "provider": GEE_PROVIDER_ID,
        "server_side_only": True,
        "mobile_runtime_dependency": False,
        "raspberry_pi_runtime_dependency": False,
        "route": {
            "source_gpx_path": str(gpx_path),
            "raw_gpx_embedded": False,
            "point_count": len(route_points),
            "total_distance_m": round(route_points[-1].distance_m, 2),
            "segment_length_m": segment_length_m,
            "buffer_m": buffer_m,
            "polyline": route_polyline,
            "buffer": route_buffer,
        },
        "segments": normalized_segments,
        "source_datasets": source_datasets,
        "date_ranges": date_ranges,
        "cloud_filtering_thresholds": dict(dataset_config.get("cloud_filtering") or {}),
        "stale_data_warnings": stale_warnings,
        "confidence_summary": confidence_summary,
        "raw_response_sha256": raw_hash,
        "blocker_reasons": blockers or list(raw_summary.get("blocker_reasons") or []),
        "counts": {
            "route_point_count": len(route_points),
            "segment_count": len(normalized_segments),
            "raw_segment_feature_count": raw_segment_count,
            "stale_warning_count": len(stale_warnings),
        },
        "boundary": {
            "candidate_only": True,
            "runtime_safety_truth": False,
            "phase1_runtime_mutation_allowed": False,
            "mobile_runtime_gee_dependency": False,
            "raspberry_pi_runtime_gee_dependency": False,
            "external_api_calls_made": external_api_calls_made,
            "server_side_export_required": True,
            "compact_route_feature_package": True,
        },
    }


def write_scout_gee_feature_package(
    *,
    gpx_path: str | Path,
    output_path: str | Path,
    project_id: str,
    prepared_at: str,
    segment_length_m: float = DEFAULT_GEE_ROUTE_SEGMENT_LENGTH_M,
    buffer_m: float = DEFAULT_GEE_ROUTE_BUFFER_M,
    dataset_config_path: str | Path | None = None,
    route_risk_geojson_path: str | Path | None = None,
    env: Mapping[str, str] | None = None,
    client: Any | None = None,
    allow_live_fetch: bool = False,
) -> dict[str, Any]:
    package = build_scout_gee_feature_package(
        gpx_path=gpx_path,
        project_id=project_id,
        prepared_at=prepared_at,
        segment_length_m=segment_length_m,
        buffer_m=buffer_m,
        dataset_config_path=dataset_config_path,
        route_risk_geojson_path=route_risk_geojson_path,
        env=env,
        client=client,
        allow_live_fetch=allow_live_fetch,
    )
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(package, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return package


_CWA_TIME_METADATA_KEYS = (
    "request_timestamp",
    "request_timestamp_hour",
    "generated_at_hour",
    "api_request_attempted",
    "api_request_attempted_at",
    "api_request_attempted_at_hour",
    "api_fetched_at",
    "api_fetched_at_hour",
    "fetched_at",
    "fetched_at_hour",
    "forecast_valid_from",
    "forecast_valid_from_hour",
    "forecast_valid_until",
    "forecast_valid_until_hour",
    "warning_valid_from",
    "warning_valid_from_hour",
    "warning_valid_until",
    "warning_valid_until_hour",
    "latest_observation_at",
    "latest_observation_at_hour",
    "valid_from",
    "valid_from_hour",
    "valid_to",
    "valid_to_hour",
    "valid_until",
    "valid_until_hour",
    "time_precision",
    "timezone",
    "time_metadata_required",
)


def _normalise_cwa_time_metadata(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        return {}
    source: Mapping[str, Any] = value
    for key in ("cwa_time_metadata", "temporal_coverage", "cwa"):
        nested = source.get(key)
        if isinstance(nested, Mapping):
            source = nested
            break
    if isinstance(source.get("cwa"), Mapping):
        source = source["cwa"]
    metadata = {
        key: source.get(key)
        for key in _CWA_TIME_METADATA_KEYS
        if key in source
    }
    if metadata and "time_precision" not in metadata:
        metadata["time_precision"] = "hour"
    if metadata and "timezone" not in metadata:
        metadata["timezone"] = "UTC"
    return metadata


def _cwa_derivative_time_properties(
    cwa_time_metadata: Mapping[str, Any],
) -> dict[str, Any]:
    metadata = _normalise_cwa_time_metadata(cwa_time_metadata)
    if not metadata:
        return {}
    properties = {
        "cwa_time_metadata": metadata,
        "source_time_metadata": {"cwa": metadata},
        "time_precision": metadata.get("time_precision", "hour"),
        "timezone": metadata.get("timezone", "UTC"),
        "cwa_api_request_attempted_at": metadata.get("api_request_attempted_at"),
        "cwa_api_request_attempted_at_hour": metadata.get(
            "api_request_attempted_at_hour"
        ),
        "cwa_api_fetched_at": metadata.get("api_fetched_at")
        or metadata.get("fetched_at"),
        "cwa_api_fetched_at_hour": metadata.get("api_fetched_at_hour")
        or metadata.get("fetched_at_hour"),
        "cwa_forecast_valid_from_hour": metadata.get("forecast_valid_from_hour"),
        "cwa_forecast_valid_until_hour": metadata.get("forecast_valid_until_hour"),
        "cwa_warning_valid_until_hour": metadata.get("warning_valid_until_hour"),
        "cwa_latest_observation_at_hour": metadata.get("latest_observation_at_hour"),
        "cwa_valid_from_hour": metadata.get("valid_from_hour"),
        "cwa_valid_until_hour": metadata.get("valid_until_hour")
        or metadata.get("valid_to_hour"),
    }
    return {key: value for key, value in properties.items() if value not in (None, "")}


def build_environment_risk_derivatives(
    feature_package: Mapping[str, Any],
    *,
    project_id: str | None = None,
    generated_at: str | None = None,
    event_date: str | None = None,
    cwa_time_metadata: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build candidate-only route environmental risk derivatives.

    These are planning evidence layers derived from the compact GEE feature
    package. They are intentionally not runtime safety truth.
    """

    resolved_project_id = str(project_id or feature_package.get("project_id") or "")
    resolved_generated_at = str(
        generated_at or feature_package.get("generated_at") or _utc_iso_now()
    )
    source_datasets = [
        dict(item)
        for item in feature_package.get("source_datasets", [])
        if isinstance(item, Mapping)
    ]
    resolved_cwa_time_metadata = _normalise_cwa_time_metadata(
        cwa_time_metadata
        or feature_package.get("cwa_time_metadata")
        or feature_package.get("temporal_coverage")
        or {}
    )
    route = feature_package.get("route") if isinstance(feature_package.get("route"), Mapping) else {}
    route_buffer = route.get("buffer") if isinstance(route.get("buffer"), Mapping) else {}
    route_buffer_m = _optional_float(route.get("buffer_m"))
    segments = [
        dict(segment)
        for segment in feature_package.get("segments", [])
        if isinstance(segment, Mapping)
    ]

    collections = {
        "new_landslide_candidates": _empty_derivative_collection(
            "new_landslide_candidates",
            resolved_project_id,
            resolved_generated_at,
            source_datasets,
            cwa_time_metadata=resolved_cwa_time_metadata,
        ),
        "wetness_flash_flood_susceptibility": _empty_derivative_collection(
            "wetness_flash_flood_susceptibility",
            resolved_project_id,
            resolved_generated_at,
            source_datasets,
            cwa_time_metadata=resolved_cwa_time_metadata,
        ),
        "trail_obscurity_risk": _empty_derivative_collection(
            "trail_obscurity_risk",
            resolved_project_id,
            resolved_generated_at,
            source_datasets,
            cwa_time_metadata=resolved_cwa_time_metadata,
        ),
        "practical_darkness_time": _empty_derivative_collection(
            "practical_darkness_time",
            resolved_project_id,
            resolved_generated_at,
            source_datasets,
            cwa_time_metadata=resolved_cwa_time_metadata,
        ),
    }
    candidates_by_kind: dict[str, list[dict[str, Any]]] = {
        key: [] for key in collections
    }
    skipped_missing_geometry = 0
    for segment in segments:
        geometry = segment.get("geometry")
        if not isinstance(geometry, Mapping):
            skipped_missing_geometry += 1
            continue
        for kind, candidate in (
            ("new_landslide_candidates", _new_landslide_candidate(segment)),
            (
                "wetness_flash_flood_susceptibility",
                _wetness_flash_flood_candidate(segment),
            ),
            ("trail_obscurity_risk", _trail_obscurity_candidate(segment)),
            ("practical_darkness_time", _practical_darkness_candidate(segment)),
        ):
            if candidate is None:
                continue
            feature = {
                "type": "Feature",
                "geometry": dict(geometry),
                "properties": {
                    **candidate,
                    "project_id": resolved_project_id,
                    "source_segment_id": segment.get("segment_id"),
                    "segment_index": segment.get("index"),
                    "start_distance_m": segment.get("start_distance_m"),
                    "end_distance_m": segment.get("end_distance_m"),
                    "mid_distance_m": segment.get("mid_distance_m"),
                    "center_lat": segment.get("center_lat"),
                    "center_lon": segment.get("center_lon"),
                    "source": "scout_gee_feature_package",
                    "source_schema_version": feature_package.get("schema_version"),
                    "source_raw_response_sha256": feature_package.get(
                        "raw_response_sha256"
                    ),
                    "candidate_only": True,
                    "runtime_safety_truth": False,
                    **(
                        _cwa_derivative_time_properties(resolved_cwa_time_metadata)
                        if kind == "wetness_flash_flood_susceptibility"
                        else {}
                    ),
                },
            }
            collections[kind]["features"].append(feature)
            candidates_by_kind[kind].append(feature)

    for kind, collection in collections.items():
        collection["counts"] = {
            "feature_count": len(collection["features"]),
            "segment_count": len(segments),
            "skipped_missing_geometry_count": skipped_missing_geometry,
        }
        collection["summary"] = _candidate_collection_summary(collection["features"])

    revalidation_report = _route_revalidation_report(
        project_id=resolved_project_id,
        generated_at=resolved_generated_at,
        event_date=event_date,
        route_buffer_m=route_buffer_m,
        route_buffer=route_buffer,
        source_datasets=source_datasets,
        collections=collections,
    )
    counts = {
        "segment_count": len(segments),
        "new_landslide_candidate_count": len(
            candidates_by_kind["new_landslide_candidates"]
        ),
        "wetness_flash_flood_candidate_count": len(
            candidates_by_kind["wetness_flash_flood_susceptibility"]
        ),
        "trail_obscurity_candidate_count": len(
            candidates_by_kind["trail_obscurity_risk"]
        ),
        "practical_darkness_candidate_count": len(
            candidates_by_kind["practical_darkness_time"]
        ),
        "skipped_missing_geometry_count": skipped_missing_geometry,
    }
    source_metric_gaps = _source_metric_gaps(segments)
    status = "ready" if segments else "missing_source"
    if segments and source_metric_gaps:
        status = "ready_with_data_gaps"
    return {
        "artifact_kind": "scout_environment_risk_derivatives",
        "schema_version": SCOUT_ENVIRONMENT_RISK_DERIVATIVE_VERSION,
        "project_id": resolved_project_id,
        "generated_at": resolved_generated_at,
        "status": status,
        "provider": GEE_PROVIDER_ID,
        "source_feature_package_schema_version": feature_package.get("schema_version"),
        "source_raw_response_sha256": feature_package.get("raw_response_sha256"),
        "source_datasets": source_datasets,
        "source_metric_gaps": source_metric_gaps,
        "source_time_metadata": {"cwa": resolved_cwa_time_metadata}
        if resolved_cwa_time_metadata
        else {},
        "cwa_time_metadata": resolved_cwa_time_metadata,
        "temporal_coverage": {"cwa": resolved_cwa_time_metadata}
        if resolved_cwa_time_metadata
        else {},
        "route_buffer_m": route_buffer_m,
        "counts": counts,
        "headline": _derivative_headline(counts, route_buffer_m),
        "collections": collections,
        "route_revalidation_report": revalidation_report,
        "boundary": {
            "candidate_only": True,
            "runtime_safety_truth": False,
            "phase1_runtime_mutation_allowed": False,
            "phase2_brain_writeback_allowed": False,
            "server_side_gee_package_required": True,
            "mobile_runtime_gee_dependency": False,
            "raspberry_pi_runtime_gee_dependency": False,
        },
    }


def write_environment_risk_derivative_artifacts(
    *,
    feature_package: Mapping[str, Any],
    output_dir: str | Path,
    project_id: str | None = None,
    generated_at: str | None = None,
    event_date: str | None = None,
    cwa_time_metadata: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    derivatives = build_environment_risk_derivatives(
        feature_package,
        project_id=project_id,
        generated_at=generated_at,
        event_date=event_date,
        cwa_time_metadata=cwa_time_metadata,
    )
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    collection_files = {
        "new_landslide_candidates": "new_landslide_candidates.geojson",
        "wetness_flash_flood_susceptibility": (
            "wetness_flash_flood_susceptibility.geojson"
        ),
        "trail_obscurity_risk": "trail_obscurity_risk.geojson",
        "practical_darkness_time": "practical_darkness_time.geojson",
    }
    refs: dict[str, str] = {}
    for key, filename in collection_files.items():
        path = out / filename
        path.write_text(
            json.dumps(
                derivatives["collections"][key],
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        refs[f"{key}_ref"] = filename
    report_path = out / "route_revalidation_report.json"
    report_path.write_text(
        json.dumps(
            derivatives["route_revalidation_report"],
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    refs["route_revalidation_report_ref"] = report_path.name
    summary = {
        **{k: v for k, v in derivatives.items() if k not in {"collections"}},
        "output_refs": refs,
    }
    summary_path = out / "environment_risk_derivatives.json"
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return summary


def _empty_derivative_collection(
    layer_key: str,
    project_id: str,
    generated_at: str,
    source_datasets: list[dict[str, Any]],
    *,
    cwa_time_metadata: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    resolved_cwa_time_metadata = _normalise_cwa_time_metadata(cwa_time_metadata or {})
    return {
        "type": "FeatureCollection",
        "artifact_kind": f"scout_{layer_key}",
        "schema_version": SCOUT_ENVIRONMENT_RISK_DERIVATIVE_VERSION,
        "project_id": project_id,
        "generated_at": generated_at,
        "layer_key": layer_key,
        "source_datasets": source_datasets,
        "source_time_metadata": {"cwa": resolved_cwa_time_metadata}
        if resolved_cwa_time_metadata
        else {},
        "cwa_time_metadata": resolved_cwa_time_metadata,
        "temporal_coverage": {"cwa": resolved_cwa_time_metadata}
        if resolved_cwa_time_metadata
        else {},
        "features": [],
        "boundary": {
            "candidate_only": True,
            "runtime_safety_truth": False,
            "phase1_runtime_mutation_allowed": False,
        },
    }


def _new_landslide_candidate(segment: Mapping[str, Any]) -> dict[str, Any] | None:
    ndvi = _nested_float(segment, "sentinel2_indices", "ndvi")
    bsi = _nested_float(segment, "sentinel2_indices", "bsi")
    bare = _nested_float(segment, "dynamic_world_probabilities", "bare")
    slope = _optional_float(segment.get("slope_deg"))
    s2_change = _optional_float(segment.get("sentinel2_before_after_change_score"))
    s1_anomaly = _optional_float(
        segment.get("sentinel1_before_after_backscatter_anomaly_db")
    )
    bare_signal = _max_available(
        bare,
        _scale_positive(bsi, low=0.10, high=0.45),
        None if ndvi is None else _clamp01((0.55 - ndvi) / 0.45),
    )
    metrics = {
        "sentinel2_change": _scale_positive(s2_change, low=0.12, high=0.45),
        "bare_soil": bare_signal,
        "sentinel1_backscatter_change": None
        if s1_anomaly is None
        else _clamp01(abs(s1_anomaly) / 4.0),
        "dem_slope": _scale_positive(slope, low=25.0, high=45.0),
    }
    score, missing = _weighted_score(
        metrics,
        {
            "sentinel2_change": 0.35,
            "bare_soil": 0.25,
            "sentinel1_backscatter_change": 0.20,
            "dem_slope": 0.20,
        },
    )
    if score is None or score < 0.55:
        return None
    if len(metrics) - len(missing) < 3:
        return None
    return _candidate_properties(
        kind="new_landslide_candidate",
        label=_distance_label(segment, "新崩塌候選"),
        score=score,
        confidence=_confidence_band(score, missing),
        stale_risk="high",
        rule_version="scout_new_landslide_candidate.v0.1",
        supporting_metrics={
            "ndvi": ndvi,
            "bare_soil_index": bsi,
            "dynamic_world_bare": bare,
            "slope_deg": slope,
            "sentinel2_before_after_change_score": s2_change,
            "sentinel1_before_after_backscatter_anomaly_db": s1_anomaly,
        },
        missing_metrics=missing,
        rationale=(
            "Sentinel-2 before/after change, bare-soil signal, Sentinel-1 "
            "backscatter anomaly, and DEM slope support a new exposed-slope "
            "candidate."
        ),
    )


def _wetness_flash_flood_candidate(segment: Mapping[str, Any]) -> dict[str, Any] | None:
    rain = _optional_float(segment.get("gpm_recent_rainfall_mm"))
    anomaly = _optional_float(segment.get("chirps_rainfall_anomaly"))
    flow = _optional_float(segment.get("flow_accumulation_proxy"))
    slope = _optional_float(segment.get("slope_deg"))
    ndwi = _nested_float(segment, "sentinel2_indices", "ndwi")
    metrics = {
        "gpm_recent_rainfall": _scale_positive(rain, low=30.0, high=160.0),
        "chirps_anomaly": _scale_positive(anomaly, low=0.5, high=2.5),
        "dem_flow_accumulation": None
        if flow is None
        else _clamp01(math.log10(max(flow, 1.0)) / 5.0),
        "terrain_runoff_slope": _scale_positive(slope, low=18.0, high=42.0),
        "surface_water_signal": _scale_positive(ndwi, low=0.0, high=0.35),
    }
    score, missing = _weighted_score(
        metrics,
        {
            "gpm_recent_rainfall": 0.35,
            "chirps_anomaly": 0.20,
            "dem_flow_accumulation": 0.25,
            "terrain_runoff_slope": 0.10,
            "surface_water_signal": 0.10,
        },
    )
    if score is None or score < 0.50:
        return None
    if len(metrics) - len(missing) < 2:
        return None
    return _candidate_properties(
        kind="wetness_flash_flood_susceptibility",
        label=_distance_label(segment, "濕滑/溪溝暴漲候選"),
        score=score,
        confidence=_confidence_band(score, missing),
        stale_risk="high",
        rule_version="scout_wetness_flash_flood.v0.1",
        supporting_metrics={
            "gpm_recent_rainfall_mm": rain,
            "chirps_rainfall_anomaly": anomaly,
            "flow_accumulation_proxy": flow,
            "slope_deg": slope,
            "ndwi": ndwi,
        },
        missing_metrics=missing,
        rationale=(
            "Recent GPM rainfall, CHIRPS anomaly, and DEM drainage proxy "
            "support a wetness or short-duration flash-flood susceptibility "
            "candidate."
        ),
    )


def _trail_obscurity_candidate(segment: Mapping[str, Any]) -> dict[str, Any] | None:
    ndvi = _nested_float(segment, "sentinel2_indices", "ndvi")
    trees = _nested_float(segment, "dynamic_world_probabilities", "trees")
    shrub = _nested_float(segment, "dynamic_world_probabilities", "shrub_and_scrub")
    gpx_density = _optional_float(
        segment.get("reference_gpx_density_per_100m")
        or segment.get("gpx_density_per_100m")
    )
    vegetation = _max_available(
        trees,
        shrub,
        None if trees is None or shrub is None else min(1.0, trees + shrub),
    )
    metrics = {
        "dynamic_world_trees_shrub": vegetation,
        "sentinel2_ndvi": _scale_positive(ndvi, low=0.45, high=0.80),
        "low_gpx_density": None
        if gpx_density is None
        else _clamp01((3.0 - gpx_density) / 3.0),
    }
    score, missing = _weighted_score(
        metrics,
        {
            "dynamic_world_trees_shrub": 0.45,
            "sentinel2_ndvi": 0.35,
            "low_gpx_density": 0.20,
        },
    )
    if score is None or score < 0.58:
        return None
    available = len(metrics) - len(missing)
    if available < 2:
        return None
    return _candidate_properties(
        kind="trail_obscurity_risk",
        label=_distance_label(segment, "路跡不明候選"),
        score=score,
        confidence=_confidence_band(score, missing),
        stale_risk="medium",
        rule_version="scout_trail_obscurity.v0.1",
        supporting_metrics={
            "ndvi": ndvi,
            "dynamic_world_trees": trees,
            "dynamic_world_shrub_and_scrub": shrub,
            "reference_gpx_density_per_100m": gpx_density,
        },
        missing_metrics=missing,
        rationale=(
            "Dynamic World vegetation probability, Sentinel-2 NDVI, and "
            "reference GPX density indicate possible trail obscurity."
        ),
    )


def _practical_darkness_candidate(segment: Mapping[str, Any]) -> dict[str, Any] | None:
    slope = _optional_float(segment.get("slope_deg"))
    ruggedness = _optional_float(segment.get("terrain_ruggedness"))
    terrain_position = _optional_float(segment.get("terrain_position_proxy"))
    aspect = _optional_float(segment.get("aspect_deg"))
    horizon_proxy = _max_available(
        _scale_positive(slope, low=20.0, high=55.0),
        _scale_positive(ruggedness, low=45.0, high=100.0),
        None if terrain_position is None else _clamp01(abs(terrain_position)),
    )
    metrics = {
        "dem_horizon_angle_proxy": horizon_proxy,
        "terrain_slope": _scale_positive(slope, low=20.0, high=55.0),
        "terrain_ruggedness": _scale_positive(ruggedness, low=45.0, high=100.0),
        "aspect_available": None if aspect is None else 1.0,
    }
    score, missing = _weighted_score(
        metrics,
        {
            "dem_horizon_angle_proxy": 0.50,
            "terrain_slope": 0.20,
            "terrain_ruggedness": 0.20,
            "aspect_available": 0.10,
        },
    )
    if score is None or score < 0.55:
        return None
    advance_min = round(15.0 + 75.0 * score, 1)
    return _candidate_properties(
        kind="practical_darkness_time",
        label=_distance_label(segment, "日落地形遮蔽候選"),
        score=score,
        confidence=_confidence_band(score, missing),
        stale_risk="medium",
        rule_version="scout_practical_darkness_time.v0.1",
        supporting_metrics={
            "slope_deg": slope,
            "terrain_ruggedness": ruggedness,
            "terrain_position_proxy": terrain_position,
            "aspect_deg": aspect,
            "estimated_darkness_advance_min": advance_min,
        },
        missing_metrics=[*missing, "route_eta", "sun_azimuth", "sun_elevation"],
        rationale=(
            "DEM-derived terrain enclosure suggests practical darkness may "
            "arrive before official sunset; final timing needs route ETA and "
            "solar geometry."
        ),
        extra={"estimated_darkness_advance_min": advance_min},
    )


def _candidate_properties(
    *,
    kind: str,
    label: str,
    score: float,
    confidence: str,
    stale_risk: str,
    rule_version: str,
    supporting_metrics: dict[str, Any],
    missing_metrics: list[str],
    rationale: str,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "candidate_kind": kind,
        "label": label,
        "score": round(score, 4),
        "severity": _severity(score),
        "confidence": confidence,
        "stale_risk": stale_risk,
        "conversion_rule_version": rule_version,
        "supporting_metrics": supporting_metrics,
        "missing_metrics": sorted(set(missing_metrics)),
        "rationale": rationale,
        **(extra or {}),
    }


def _route_revalidation_report(
    *,
    project_id: str,
    generated_at: str,
    event_date: str | None,
    route_buffer_m: float | None,
    route_buffer: Mapping[str, Any],
    source_datasets: list[dict[str, Any]],
    collections: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    counts = {
        key: len(collection.get("features", []))
        for key, collection in collections.items()
    }
    status = "ready" if event_date else "needs_event_date"
    notes = [
        "Route revalidation is candidate-only and requires human review.",
        (
            "event_date not supplied; before/after windows fall back to the "
            "GEE feature package date ranges and should be rerun for a named "
            "earthquake or typhoon event."
            if not event_date
            else "event_date supplied; rerun GEE composites around the event for final review."
        ),
    ]
    return {
        "artifact_kind": "scout_route_revalidation_report",
        "schema_version": SCOUT_ENVIRONMENT_RISK_DERIVATIVE_VERSION,
        "project_id": project_id,
        "generated_at": generated_at,
        "event_date": event_date,
        "status": status,
        "route_buffer_m": route_buffer_m,
        "route_buffer": route_buffer,
        "source_datasets": source_datasets,
        "counts": counts,
        "headline": _derivative_headline(
            {
                "new_landslide_candidate_count": counts.get(
                    "new_landslide_candidates", 0
                ),
                "wetness_flash_flood_candidate_count": counts.get(
                    "wetness_flash_flood_susceptibility", 0
                ),
                "trail_obscurity_candidate_count": counts.get(
                    "trail_obscurity_risk", 0
                ),
                "practical_darkness_candidate_count": counts.get(
                    "practical_darkness_time", 0
                ),
            },
            route_buffer_m,
        ),
        "notes": notes,
        "candidate_only": True,
        "runtime_safety_truth": False,
    }


def _candidate_collection_summary(features: list[dict[str, Any]]) -> dict[str, Any]:
    if not features:
        return {"feature_count": 0, "max_score": None, "high_count": 0}
    scores = [
        _optional_float(feature.get("properties", {}).get("score"))
        for feature in features
        if isinstance(feature.get("properties"), Mapping)
    ]
    scores = [score for score in scores if score is not None]
    return {
        "feature_count": len(features),
        "max_score": round(max(scores), 4) if scores else None,
        "high_count": sum(
            1
            for feature in features
            if feature.get("properties", {}).get("severity") == "high"
        ),
        "top_labels": [
            str(feature.get("properties", {}).get("label"))
            for feature in sorted(
                features,
                key=lambda item: _optional_float(
                    item.get("properties", {}).get("score")
                )
                or 0.0,
                reverse=True,
            )[:5]
        ],
    }


def _source_metric_gaps(segments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    keys = {
        "sentinel2": (
            ("sentinel2_indices", "ndvi"),
            ("sentinel2_indices", "bsi"),
            ("sentinel2_before_after_change_score",),
        ),
        "sentinel1": (("sentinel1_before_after_backscatter_anomaly_db",),),
        "dynamic_world": (
            ("dynamic_world_probabilities", "trees"),
            ("dynamic_world_probabilities", "shrub_and_scrub"),
            ("dynamic_world_probabilities", "bare"),
        ),
        "rainfall": (("gpm_recent_rainfall_mm",), ("chirps_rainfall_anomaly",)),
        "terrain": (
            ("slope_deg",),
            ("terrain_ruggedness",),
            ("flow_accumulation_proxy",),
        ),
    }
    gaps: list[dict[str, Any]] = []
    total = len(segments)
    if total == 0:
        return gaps
    for family, paths in keys.items():
        present = sum(
            1
            for segment in segments
            if any(_value_at_path(segment, path) is not None for path in paths)
        )
        if present < total:
            gaps.append(
                {
                    "metric_family": family,
                    "missing_segment_count": total - present,
                    "segment_count": total,
                    "missing_ratio": round((total - present) / total, 4),
                }
            )
    return gaps


def _derivative_headline(counts: Mapping[str, Any], route_buffer_m: float | None) -> str:
    buffer_label = f"{int(route_buffer_m)}m buffer" if route_buffer_m else "route buffer"
    landslide = int(counts.get("new_landslide_candidate_count") or 0)
    wetness = int(counts.get("wetness_flash_flood_candidate_count") or 0)
    obscurity = int(counts.get("trail_obscurity_candidate_count") or 0)
    darkness = int(counts.get("practical_darkness_candidate_count") or 0)
    return (
        f"這條路線 {buffer_label} 內目前產生 {landslide} 處新崩塌候選、"
        f"{wetness} 處濕滑/溪溝暴漲候選、{obscurity} 處路跡不明候選、"
        f"{darkness} 處日落地形遮蔽候選；全部仍是 pretrip candidate evidence。"
    )


def _distance_label(segment: Mapping[str, Any], prefix: str) -> str:
    distance = _optional_float(segment.get("mid_distance_m"))
    if distance is None:
        return prefix
    return f"{prefix} {distance / 1000.0:.1f}K"


def _severity(score: float) -> str:
    return "high" if score >= 0.75 else "medium" if score >= 0.55 else "low"


def _confidence_band(score: float, missing: list[str]) -> str:
    if len(missing) >= 3:
        return "low"
    if score >= 0.75 and not missing:
        return "high"
    if score >= 0.55:
        return "medium"
    return "low"


def _weighted_score(
    metrics: Mapping[str, float | None],
    weights: Mapping[str, float],
) -> tuple[float | None, list[str]]:
    score = 0.0
    weight_total = 0.0
    missing: list[str] = []
    for key, weight in weights.items():
        value = metrics.get(key)
        if value is None:
            missing.append(key)
            continue
        score += _clamp01(value) * weight
        weight_total += weight
    if weight_total <= 0:
        return None, missing
    return score / weight_total, missing


def _max_available(*values: float | None) -> float | None:
    present = [value for value in values if value is not None]
    if not present:
        return None
    return max(_clamp01(value) for value in present)


def _scale_positive(value: Any, *, low: float, high: float) -> float | None:
    number = _optional_float(value)
    if number is None:
        return None
    if high <= low:
        return None
    return _clamp01((number - low) / (high - low))


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def _nested_float(payload: Mapping[str, Any], key: str, nested_key: str) -> float | None:
    nested = payload.get(key)
    if not isinstance(nested, Mapping):
        return None
    return _optional_float(nested.get(nested_key))


def _value_at_path(payload: Mapping[str, Any], path: tuple[str, ...]) -> Any:
    current: Any = payload
    for key in path:
        if not isinstance(current, Mapping):
            return None
        current = current.get(key)
    return current


def _utc_iso_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _validate_route_segment_length(segment_length_m: float) -> None:
    if not (
        MIN_GEE_ROUTE_SEGMENT_LENGTH_M
        <= float(segment_length_m)
        <= MAX_GEE_ROUTE_SEGMENT_LENGTH_M
    ):
        raise ValueError(
            "GEE route segment length must be between "
            f"{MIN_GEE_ROUTE_SEGMENT_LENGTH_M:.0f}m and "
            f"{MAX_GEE_ROUTE_SEGMENT_LENGTH_M:.0f}m"
        )


def _load_gpx_route_points(path: Path) -> list[GeeRoutePoint]:
    root = ET.fromstring(path.read_text(encoding="utf-8"))
    trkpts = [item for item in root.iter() if _tag_name(item.tag) == "trkpt"]
    source_points = trkpts or [item for item in root.iter() if _tag_name(item.tag) == "rtept"]
    points: list[GeeRoutePoint] = []
    cumulative = 0.0
    previous: GeeRoutePoint | None = None
    for item in source_points:
        lat_raw = item.attrib.get("lat")
        lon_raw = item.attrib.get("lon")
        if lat_raw is None or lon_raw is None:
            continue
        ele = None
        timestamp = None
        for child in item:
            child_name = _tag_name(child.tag)
            if child_name == "ele" and child.text:
                ele = _float_or_none(child.text)
            elif child_name == "time" and child.text:
                timestamp = child.text.strip()
        lat = float(lat_raw)
        lon = float(lon_raw)
        if previous is not None:
            cumulative += _haversine_m(previous.lat, previous.lon, lat, lon)
        point = GeeRoutePoint(
            lat=lat,
            lon=lon,
            elevation_m=ele,
            distance_m=cumulative,
            timestamp=timestamp,
        )
        points.append(point)
        previous = point
    return points


def _interpolate_route_point(
    points: list[GeeRoutePoint],
    distance_m: float,
) -> GeeRoutePoint:
    if distance_m <= 0:
        return points[0]
    if distance_m >= points[-1].distance_m:
        return points[-1]
    for left, right in zip(points, points[1:]):
        if left.distance_m <= distance_m <= right.distance_m:
            span = right.distance_m - left.distance_m
            ratio = 0.0 if span <= 0 else (distance_m - left.distance_m) / span
            elevation = None
            if left.elevation_m is not None and right.elevation_m is not None:
                elevation = left.elevation_m + (right.elevation_m - left.elevation_m) * ratio
            return GeeRoutePoint(
                lat=left.lat + (right.lat - left.lat) * ratio,
                lon=left.lon + (right.lon - left.lon) * ratio,
                elevation_m=elevation,
                distance_m=distance_m,
                timestamp=left.timestamp if ratio < 0.5 else right.timestamp,
            )
    return points[-1]


def _route_polyline_feature(points: list[GeeRoutePoint]) -> dict[str, Any]:
    return {
        "type": "Feature",
        "geometry": {
            "type": "LineString",
            "coordinates": [[point.lon, point.lat] for point in points],
        },
        "properties": {
            "point_count": len(points),
            "total_distance_m": round(points[-1].distance_m, 2),
            "coordinate_order": "lon_lat",
        },
    }


def _route_buffer_feature(points: list[GeeRoutePoint], *, buffer_m: float) -> dict[str, Any]:
    lats = [point.lat for point in points]
    lons = [point.lon for point in points]
    mid_lat = sum(lats) / len(lats)
    lat_pad = buffer_m / 111_320.0
    lon_pad = buffer_m / max(1.0, 111_320.0 * math.cos(math.radians(mid_lat)))
    west = min(lons) - lon_pad
    east = max(lons) + lon_pad
    south = min(lats) - lat_pad
    north = max(lats) + lat_pad
    return {
        "type": "Feature",
        "geometry": {
            "type": "Polygon",
            "coordinates": [
                [
                    [west, south],
                    [east, south],
                    [east, north],
                    [west, north],
                    [west, south],
                ]
            ],
        },
        "properties": {
            "buffer_m": buffer_m,
            "buffer_method": "route_bbox_expanded_corridor_proxy",
            "bbox_wgs84": {
                "west": west,
                "south": south,
                "east": east,
                "north": north,
            },
        },
    }


def _route_feature_date_ranges(
    dataset_config: Mapping[str, Any],
    prepared_at: str,
) -> dict[str, Any]:
    end = _parse_datetime(prepared_at)
    output: dict[str, Any] = {}
    for dataset in dataset_config.get("datasets", []):
        if not isinstance(dataset, Mapping):
            continue
        key = str(dataset.get("key") or dataset.get("dataset_id"))
        date_range = str(dataset.get("date_range") or "static")
        if date_range == "static":
            output[key] = {"type": "static"}
        elif date_range == "recent_72h":
            output[key] = _window_dict(end - timedelta(hours=72), end)
        elif date_range == "recent_7d":
            output[key] = _window_dict(end - timedelta(days=7), end)
        elif date_range == "recent_30d_vs_climatology":
            output[key] = {
                **_window_dict(end - timedelta(days=30), end),
                "baseline": "same day-of-year climatology if available",
            }
        elif date_range == "recent_90d":
            output[key] = _window_dict(end - timedelta(days=90), end)
        elif date_range == "recent_365d":
            output[key] = _window_dict(end - timedelta(days=365), end)
        elif date_range == "before_after_180d":
            output[key] = {
                "before": _window_dict(end - timedelta(days=360), end - timedelta(days=180)),
                "after": _window_dict(end - timedelta(days=90), end),
            }
        else:
            output[key] = {"type": date_range}
    return output


def _window_dict(start: datetime, end: datetime) -> dict[str, str]:
    return {
        "start": start.isoformat().replace("+00:00", "Z"),
        "end": end.isoformat().replace("+00:00", "Z"),
    }


def _route_feature_job_expression(
    *,
    route_polyline: dict[str, Any],
    route_buffer: dict[str, Any],
    segments: list[dict[str, Any]],
    dataset_config: Mapping[str, Any],
    date_ranges: Mapping[str, Any],
    prepared_at: str,
) -> dict[str, Any]:
    # v0.1 compiles a deterministic server-side job manifest. The REST client
    # expects a Scout-owned GEE script/service to compute the segment metrics and
    # return the same manifest shape with segment_features populated.
    return _expression_graph(
        _const(
            {
                "job_kind": "scout_gee_route_feature_package",
                "job_version": SCOUT_GEE_FEATURE_PACKAGE_VERSION,
                "prepared_at": prepared_at,
                "route_polyline": route_polyline,
                "route_buffer": route_buffer,
                "segments": segments,
                "dataset_config": dict(dataset_config),
                "date_ranges": dict(date_ranges),
                "expected_output": "segment_features",
            }
        )
    )


def _normalize_route_feature_segments(
    *,
    raw_summary: Mapping[str, Any],
    route_segments: list[GeeRouteSegment],
    dataset_config: Mapping[str, Any],
    date_ranges: Mapping[str, Any],
    risk_samples: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    raw_features = _extract_raw_segment_features(raw_summary)
    by_id = {
        str(item.get("segment_id")): item
        for item in raw_features
        if isinstance(item, Mapping) and item.get("segment_id") is not None
    }
    warnings: list[dict[str, Any]] = []
    output: list[dict[str, Any]] = []
    source_datasets = _source_dataset_records(dataset_config, date_ranges)
    for index, segment in enumerate(route_segments):
        raw = by_id.get(segment.segment_id)
        if raw is None and index < len(raw_features) and isinstance(raw_features[index], Mapping):
            raw = raw_features[index]
        raw = dict(raw or {})
        nearest_risk_sample = _nearest_risk_sample(segment.mid_distance_m, risk_samples)
        fallback_metrics = _applied_metric_fallback(
            raw,
            _route_risk_metric_fallback(nearest_risk_sample),
        )
        if fallback_metrics:
            raw = {**raw, **fallback_metrics}
        metrics = _segment_metric_payload(raw)
        segment_warnings = _segment_stale_warnings(segment.segment_id, raw, metrics)
        warnings.extend(segment_warnings)
        fusion = _risk_fusion_for_segment(segment, metrics, risk_samples)
        confidence = _segment_confidence(metrics, dataset_config, segment_warnings)
        metric_source_notes = _segment_metric_source_notes(fallback_metrics)
        output.append(
            {
                **segment.to_feature()["properties"],
                "geometry": segment.to_feature()["geometry"],
                **metrics,
                "risk_fusion": fusion,
                "source_datasets": source_datasets,
                "confidence": confidence,
                "metric_source_notes": metric_source_notes,
                "stale_data_warnings": segment_warnings,
                "candidate_only": True,
                "runtime_safety_truth": False,
            }
        )
    return output, warnings


def _extract_raw_segment_features(raw_summary: Mapping[str, Any]) -> list[dict[str, Any]]:
    candidates = [
        raw_summary.get("segment_features"),
        raw_summary.get("segments"),
    ]
    result = raw_summary.get("result")
    if isinstance(result, Mapping):
        candidates.extend([result.get("segment_features"), result.get("segments")])
    for candidate in candidates:
        if isinstance(candidate, list):
            return [dict(item) for item in candidate if isinstance(item, Mapping)]
    return []


def _segment_metric_payload(raw: Mapping[str, Any]) -> dict[str, Any]:
    dynamic_world = _nested_mapping(
        raw,
        "dynamic_world_probabilities",
        "dynamic_world",
        "landcover_probabilities",
    )
    sentinel2 = _nested_mapping(raw, "sentinel2_indices", "sentinel2", "s2")
    return {
        "elevation_m": _first_number(raw, "elevation_m", "elevation"),
        "slope_deg": _first_number(raw, "slope_deg", "slope_degrees", "slope"),
        "aspect_deg": _first_number(raw, "aspect_deg", "aspect"),
        "terrain_ruggedness": _first_number(
            raw,
            "terrain_ruggedness",
            "ruggedness",
            "tri",
        ),
        "curvature_proxy": _first_number(raw, "curvature_proxy", "curvature"),
        "terrain_position_proxy": _first_number(
            raw,
            "terrain_position_proxy",
            "terrain_position",
            "tpi",
        ),
        "flow_accumulation_proxy": _first_number(
            raw,
            "flow_accumulation_proxy",
            "flow_accumulation",
        ),
        "dynamic_world_probabilities": _clean_probability_mapping(dynamic_world),
        "sentinel2_indices": {
            "ndvi": _first_number(sentinel2, "ndvi"),
            "bsi": _first_number(sentinel2, "bsi", "bare_soil_index"),
            "ndwi": _first_number(sentinel2, "ndwi"),
            "nbr": _first_number(sentinel2, "nbr"),
        },
        "sentinel2_before_after_change_score": _first_number(
            raw,
            "sentinel2_before_after_change_score",
            "sentinel2_change_score",
            "s2_change_score",
        ),
        "sentinel1_before_after_backscatter_anomaly_db": _first_number(
            raw,
            "sentinel1_before_after_backscatter_anomaly_db",
            "sentinel1_backscatter_anomaly_db",
            "s1_backscatter_anomaly_db",
        ),
        "gpm_recent_rainfall_mm": _first_number(
            raw,
            "gpm_recent_rainfall_mm",
            "recent_rainfall_mm",
            "last_72h_mm",
        ),
        "chirps_rainfall_anomaly": _first_number(
            raw,
            "chirps_rainfall_anomaly",
            "rainfall_anomaly",
            "chirps_anomaly",
        ),
        "nearest_firms_active_fire_distance_m": _first_number(
            raw,
            "nearest_firms_active_fire_distance_m",
            "firms_distance_m",
            "active_fire_distance_m",
        ),
        "sentinel2_cloud_free_count": _first_number(
            raw,
            "sentinel2_cloud_free_count",
            "s2_cloud_free_count",
            "cloud_free_count",
        ),
    }


def _route_risk_metric_fallback(sample: Mapping[str, Any]) -> dict[str, Any]:
    if not sample:
        return {}
    fallback: dict[str, Any] = {}
    elevation = _first_number(sample, "elevation_m", "elevation")
    tri = _first_number(sample, "tri", "terrain_ruggedness")
    lec = _first_number(sample, "lec", "local_escape_complexity")
    sri = _first_number(sample, "sri", "stream_risk_index")
    teii = _first_number(sample, "teii_20m", "teii")
    if elevation is not None:
        fallback["elevation_m"] = elevation
    if tri is not None:
        fallback["terrain_ruggedness"] = tri
    if lec is not None:
        # LEC（低容錯/逃脫複雜度 proxy）is not slope. This bounded slope
        # proxy only keeps terrain-derived derivatives useful while live GEE
        # route metrics are unavailable.
        fallback["slope_deg"] = round(max(0.0, min(45.0, lec / 100.0 * 45.0)), 2)
    if sri is not None:
        fallback["flow_accumulation_proxy"] = round(max(0.0, sri) * 100.0, 2)
    if teii is not None:
        fallback["terrain_position_proxy"] = round(max(0.0, min(1.0, teii / 100.0)), 4)
    if fallback:
        fallback["metric_fallback_source"] = "scout_risk_engine_route_profile"
        fallback["metric_fallback_note"] = (
            "Terrain proxy from Scout Risk Engine route profile; Sentinel, "
            "Dynamic World, CHIRPS, and true GEE per-segment metrics remain "
            "missing until the route-level GEE job succeeds."
        )
    return fallback


def _applied_metric_fallback(
    raw: Mapping[str, Any],
    fallback: Mapping[str, Any],
) -> dict[str, Any]:
    if not fallback:
        return {}
    applied: dict[str, Any] = {}
    for key, value in fallback.items():
        if key in {"metric_fallback_source", "metric_fallback_note"}:
            continue
        if raw.get(key) is None:
            applied[key] = value
    if not applied:
        return {}
    applied["metric_fallback_source"] = fallback.get("metric_fallback_source")
    applied["metric_fallback_note"] = fallback.get("metric_fallback_note")
    return applied


def _segment_metric_source_notes(
    fallback_metrics: Mapping[str, Any],
) -> list[dict[str, Any]]:
    if not fallback_metrics:
        return []
    fallback_keys = sorted(
        key
        for key in fallback_metrics
        if key not in {"metric_fallback_source", "metric_fallback_note"}
    )
    return [
        {
            "source_kind": fallback_metrics.get("metric_fallback_source"),
            "fields": fallback_keys,
            "note": fallback_metrics.get("metric_fallback_note"),
            "candidate_only": True,
            "runtime_safety_truth": False,
        }
    ]


def _segment_stale_warnings(
    segment_id: str,
    raw: Mapping[str, Any],
    metrics: Mapping[str, Any],
) -> list[dict[str, Any]]:
    warnings: list[dict[str, Any]] = []
    cloud_free_count = metrics.get("sentinel2_cloud_free_count")
    sentinel_status = str(
        raw.get("sentinel2_status") or raw.get("s2_status") or ""
    ).lower()
    if cloud_free_count == 0 or sentinel_status in {
        "no_cloud_free_imagery",
        "stale",
        "missing",
    }:
        warnings.append(
            {
                "segment_id": segment_id,
                "layer": "sentinel2",
                "warning": "no_cloud_free_sentinel2_imagery",
                "message": (
                    "Sentinel-derived vegetation, bare-soil, water, and change "
                    "features are stale or unavailable for this segment."
                ),
                "candidate_only": True,
            }
        )
    return warnings


def _risk_fusion_for_segment(
    segment: GeeRouteSegment,
    metrics: Mapping[str, Any],
    risk_samples: list[dict[str, Any]],
) -> dict[str, Any]:
    nearest = _nearest_risk_sample(segment.mid_distance_m, risk_samples)
    teii = _first_number(nearest, "teii_20m", "teii")
    weather_risk = _first_number(nearest, "WeatherRisk", "weatherRisk", "weather_risk")
    daylight_raw = nearest.get("DaylightRisk") or nearest.get("daylightRisk") or nearest.get("daylight_risk")
    daylight_risk = _daylight_score(daylight_raw)
    terrain_proxy = _gee_terrain_risk_proxy(metrics)
    weather_proxy = _gee_weather_risk_proxy(metrics)
    if weather_risk is None:
        weather_risk = weather_proxy
    interaction_risk = _first_number(
        nearest,
        "InteractionRisk",
        "interactionRisk",
        "interaction_risk",
    )
    teii_norm = (teii / 100.0) if teii is not None else terrain_proxy
    if interaction_risk is None:
        interaction_risk = round(teii_norm * (weather_risk or 0.0), 4)
    daylight_component = daylight_risk if daylight_risk is not None else 0.0
    route_environment_risk = round(
        min(
            1.0,
            0.45 * teii_norm
            + 0.25 * (weather_risk or 0.0)
            + 0.15 * daylight_component
            + 0.15 * interaction_risk,
        ),
        4,
    )
    return {
        "fusion_version": "scout_gee_risk_fusion.v0.1",
        "teii_20m": teii,
        "WeatherRisk": weather_risk,
        "DaylightRisk": daylight_raw,
        "DaylightRisk_score": daylight_risk,
        "InteractionRisk": interaction_risk,
        "gee_terrain_risk_proxy": round(terrain_proxy, 4),
        "gee_weather_risk_proxy": round(weather_proxy, 4),
        "route_environment_risk": route_environment_risk,
        "source": "nearest_route_risk_sample_plus_gee_segment_features",
        "candidate_only": True,
        "runtime_safety_truth": False,
    }


def _gee_terrain_risk_proxy(metrics: Mapping[str, Any]) -> float:
    slope = _optional_float(metrics.get("slope_deg")) or 0.0
    ruggedness = _optional_float(metrics.get("terrain_ruggedness")) or 0.0
    flow = _optional_float(metrics.get("flow_accumulation_proxy")) or 0.0
    change = abs(_optional_float(metrics.get("sentinel2_before_after_change_score")) or 0.0)
    s1 = abs(_optional_float(metrics.get("sentinel1_before_after_backscatter_anomaly_db")) or 0.0)
    return min(
        1.0,
        max(
            slope / 45.0,
            ruggedness / 100.0,
            math.log10(max(flow, 1.0)) / 6.0,
            change,
            s1 / 6.0,
        ),
    )


def _gee_weather_risk_proxy(metrics: Mapping[str, Any]) -> float:
    rain = _optional_float(metrics.get("gpm_recent_rainfall_mm")) or 0.0
    anomaly = max(0.0, _optional_float(metrics.get("chirps_rainfall_anomaly")) or 0.0)
    fire_distance = _optional_float(metrics.get("nearest_firms_active_fire_distance_m"))
    fire = 0.0
    if fire_distance is not None:
        fire = max(0.0, min(1.0, (5000.0 - fire_distance) / 5000.0))
    return min(1.0, rain / 200.0 + anomaly / 3.0 * 0.25 + fire * 0.25)


def _segment_confidence(
    metrics: Mapping[str, Any],
    dataset_config: Mapping[str, Any],
    warnings: list[dict[str, Any]],
) -> dict[str, Any]:
    per_dataset: dict[str, float] = {}
    for dataset in dataset_config.get("datasets", []):
        if isinstance(dataset, Mapping):
            value = _optional_float(dataset.get("confidence"))
            if value is not None:
                per_dataset[str(dataset.get("dataset_id"))] = value
    if warnings:
        for dataset_id in (
            "COPERNICUS/S2_SR_HARMONIZED",
            "GOOGLE/CLOUD_SCORE_PLUS/V1/S2_HARMONIZED",
        ):
            if dataset_id in per_dataset:
                per_dataset[dataset_id] = min(per_dataset[dataset_id], 0.35)
    available_metric_count = sum(
        1
        for key, value in metrics.items()
        if key != "dynamic_world_probabilities"
        and key != "sentinel2_indices"
        and value is not None
    )
    mean_confidence = (
        sum(per_dataset.values()) / len(per_dataset) if per_dataset else 0.0
    )
    completeness = min(1.0, available_metric_count / 12.0)
    score = round(mean_confidence * (0.55 + 0.45 * completeness), 3)
    return {
        "score": score,
        "band": "high" if score >= 0.75 else "medium" if score >= 0.5 else "low",
        "per_dataset": per_dataset,
        "available_metric_count": available_metric_count,
        "stale_warning_count": len(warnings),
    }


def _source_dataset_records(
    dataset_config: Mapping[str, Any],
    date_ranges: Mapping[str, Any],
) -> list[dict[str, Any]]:
    cloud = dict(dataset_config.get("cloud_filtering") or {})
    records: list[dict[str, Any]] = []
    for dataset in dataset_config.get("datasets", []):
        if not isinstance(dataset, Mapping):
            continue
        key = str(dataset.get("key") or dataset.get("dataset_id"))
        records.append(
            {
                "key": key,
                "dataset_id": dataset.get("dataset_id"),
                "role": dataset.get("role"),
                "bands": list(dataset.get("bands") or []),
                "date_range": date_ranges.get(key),
                "cloud_filtering_thresholds": cloud
                if key in {"sentinel2_sr", "cloud_score_plus"}
                else {},
                "confidence": dataset.get("confidence"),
                "candidate_only": True,
                "runtime_safety_truth": False,
            }
        )
    return records


def _package_confidence_summary(segments: list[dict[str, Any]]) -> dict[str, Any]:
    scores = [
        _optional_float(segment.get("confidence", {}).get("score"))
        for segment in segments
        if isinstance(segment.get("confidence"), Mapping)
    ]
    scores = [score for score in scores if score is not None]
    if not scores:
        return {"score": 0.0, "band": "low"}
    mean_score = sum(scores) / len(scores)
    return {
        "score": round(mean_score, 3),
        "band": "high" if mean_score >= 0.75 else "medium" if mean_score >= 0.5 else "low",
        "min_segment_score": round(min(scores), 3),
        "max_segment_score": round(max(scores), 3),
    }


def _load_route_risk_samples(path: str | Path | None) -> list[dict[str, Any]]:
    if path is None:
        return []
    risk_path = Path(path)
    if not risk_path.exists():
        return []
    payload = json.loads(risk_path.read_text(encoding="utf-8"))
    if isinstance(payload, Mapping) and isinstance(payload.get("features"), list):
        samples: list[dict[str, Any]] = []
        for feature in payload["features"]:
            if not isinstance(feature, Mapping):
                continue
            props = dict(feature.get("properties") or {})
            geometry = feature.get("geometry") or {}
            if isinstance(geometry, Mapping) and geometry.get("type") == "Point":
                coords = geometry.get("coordinates") or []
                if len(coords) >= 2:
                    props.setdefault("lon", coords[0])
                    props.setdefault("lat", coords[1])
            samples.append(props)
        return samples
    if isinstance(payload, Mapping) and isinstance(payload.get("samples"), list):
        return [dict(item) for item in payload["samples"] if isinstance(item, Mapping)]
    return []


def _nearest_risk_sample(
    mid_distance_m: float,
    samples: list[dict[str, Any]],
) -> dict[str, Any]:
    if not samples:
        return {}
    return min(
        samples,
        key=lambda item: abs(
            (_first_number(item, "distance_m", "mid_distance_m") or 0.0)
            - mid_distance_m
        ),
    )


def _clean_probability_mapping(mapping: Mapping[str, Any]) -> dict[str, float | None]:
    keys = (
        "water",
        "trees",
        "grass",
        "flooded_vegetation",
        "crops",
        "shrub_and_scrub",
        "built",
        "bare",
        "snow_and_ice",
    )
    return {key: _first_number(mapping, key) for key in keys}


def _nested_mapping(mapping: Mapping[str, Any], *keys: str) -> dict[str, Any]:
    for key in keys:
        value = mapping.get(key)
        if isinstance(value, Mapping):
            return dict(value)
    return {}


def _daylight_score(value: Any) -> float | None:
    if value is None:
        return None
    number = _optional_float(value)
    if number is not None:
        return number if number <= 1 else number / 100.0
    text = str(value).strip().lower()
    return {
        "low": 0.2,
        "medium": 0.5,
        "moderate": 0.5,
        "high": 0.8,
        "critical": 1.0,
        "unknown": 0.0,
    }.get(text)


def _sha256_json(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str).encode(
            "utf-8"
        )
    ).hexdigest()


def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius_m = 6_371_000.0
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    value = (
        math.sin(dphi / 2.0) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2.0) ** 2
    )
    return radius_m * 2.0 * math.atan2(math.sqrt(value), math.sqrt(1.0 - value))


def _tag_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _float_or_none(value: Any) -> float | None:
    return _optional_float(value)


def _optional_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _gee_credential_refs(active_env: Mapping[str, str], auth_mode: str) -> list[str]:
    candidate_envs = [
        SCOUT_GEE_CREDENTIALS_PATH_ENV,
        GOOGLE_APPLICATION_CREDENTIALS_ENV,
        EARTHENGINE_TOKEN_ENV,
    ]
    refs = [
        f"env:{env_name}"
        for env_name in candidate_envs
        if str(active_env.get(env_name, "")).strip()
    ]
    if refs:
        return refs
    if auth_mode == "adc" and _truthy(active_env.get("SCOUT_GEE_ASSUME_ADC")):
        return ["runtime:application_default_credentials"]
    return []


def _gee_access_token(active_env: Mapping[str, str]) -> str:
    direct_token = str(active_env.get(EARTHENGINE_TOKEN_ENV, "")).strip()
    if direct_token:
        return direct_token
    credential_path = str(active_env.get(SCOUT_GEE_CREDENTIALS_PATH_ENV, "")).strip()
    google_credential_path = str(
        active_env.get(GOOGLE_APPLICATION_CREDENTIALS_ENV, "")
    ).strip()
    path = credential_path or google_credential_path
    if not path:
        raise GeeFetchError(["missing_gee_credentials_path"])
    path = str(Path(path).expanduser())
    try:
        credential_payload = _json_loads_bytes(open(path, "rb").read())
    except FileNotFoundError as exc:
        raise GeeFetchError(["missing_gee_credentials_file"]) from exc
    except Exception as exc:
        raise GeeFetchError([f"invalid_gee_credentials_file:{type(exc).__name__}"]) from exc

    refresh_token = str(credential_payload.get("refresh_token", "")).strip()
    if refresh_token:
        return _refresh_user_oauth_token(active_env, credential_payload, refresh_token)

    if credential_payload.get("type") == "service_account":
        return _service_account_access_token(path)

    access_token = str(credential_payload.get("access_token", "")).strip()
    if access_token:
        return access_token
    raise GeeFetchError(["unsupported_gee_credentials_file"])


def _refresh_user_oauth_token(
    active_env: Mapping[str, str],
    credential_payload: Mapping[str, Any],
    refresh_token: str,
) -> str:
    client_id = str(
        credential_payload.get("client_id")
        or active_env.get(SCOUT_GEE_OAUTH_CLIENT_ID_ENV, "")
    ).strip()
    client_secret = str(
        credential_payload.get("client_secret")
        or active_env.get(SCOUT_GEE_OAUTH_CLIENT_SECRET_ENV, "")
    ).strip()
    if not client_id or not client_secret:
        raise GeeFetchError(["missing_gee_oauth_client_id_or_secret"])
    body = urllib.parse.urlencode(
        {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": client_id,
            "client_secret": client_secret,
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        GEE_OAUTH_TOKEN_URL,
        data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = _json_loads_bytes(response.read())
    except urllib.error.HTTPError as exc:
        raise GeeFetchError(
            [f"gee_oauth_http_error:{exc.code}"],
            raw_summary={"http_status": exc.code, "error": _safe_error_payload(exc)},
        ) from exc
    token = str(payload.get("access_token", "")).strip()
    if not token:
        raise GeeFetchError(["gee_oauth_missing_access_token"])
    return token


def _service_account_access_token(path: str) -> str:
    try:
        from google.auth.transport.requests import Request
        from google.oauth2 import service_account
    except Exception as exc:  # pragma: no cover - depends on deployment image.
        raise GeeFetchError([f"missing_google_auth_dependency:{type(exc).__name__}"]) from exc
    credentials = service_account.Credentials.from_service_account_file(
        path,
        scopes=["https://www.googleapis.com/auth/earthengine"],
    )
    credentials.refresh(Request())
    token = str(credentials.token or "").strip()
    if not token:
        raise GeeFetchError(["gee_service_account_missing_access_token"])
    return token


def _smap_l4_mean_expression(
    bbox_wgs84: Mapping[str, float],
    window: GeeFetchWindow,
) -> dict[str, Any]:
    collection = _collection_filtered_by_date("NASA/SMAP/SPL4SMGP/008", window)
    image = _fn("reduce.mean", {"collection": collection})
    return _expression_graph(
        _fn(
            "Image.reduceRegion",
            {
                "image": image,
                "reducer": _fn("Reducer.mean", {}),
                "geometry": _rectangle_geometry(bbox_wgs84),
                "scale": _const(9000),
                "bestEffort": _const(True),
                "maxPixels": _const(100000000),
                "tileScale": _const(4),
            },
        )
    )


def _gpm_imerg_sum_expression(
    bbox_wgs84: Mapping[str, float],
    window: GeeFetchWindow,
) -> dict[str, Any]:
    collection = _collection_filtered_by_date("NASA/GPM_L3/IMERG_V07", window)
    image = _fn("reduce.sum", {"collection": collection})
    return _expression_graph(
        _fn(
            "Image.reduceRegion",
            {
                "image": image,
                "reducer": _fn("Reducer.mean", {}),
                "geometry": _rectangle_geometry(bbox_wgs84),
                "scale": _const(10000),
                "bestEffort": _const(True),
                "maxPixels": _const(100000000),
                "tileScale": _const(4),
            },
        )
    )


def _collection_filtered_by_date(collection_id: str, window: GeeFetchWindow) -> dict[str, Any]:
    collection = _fn(
        "ImageCollection.load",
        {"id": _const(collection_id)},
    )
    date_filter = _fn(
        "Filter.dateRangeContains",
        {
            "leftValue": _fn(
                "DateRange",
                {
                    "start": _fn("Date", {"value": _const(_millis(window.start))}),
                    "end": _fn("Date", {"value": _const(_millis(window.end))}),
                },
            ),
            "rightField": _const("system:time_start"),
        },
    )
    return _fn("Collection.filter", {"collection": collection, "filter": date_filter})


def _rectangle_geometry(bbox_wgs84: Mapping[str, float]) -> dict[str, Any]:
    return _fn(
        "GeometryConstructors.Rectangle",
        {
            "coordinates": _const(
                [
                    float(bbox_wgs84["west"]),
                    float(bbox_wgs84["south"]),
                    float(bbox_wgs84["east"]),
                    float(bbox_wgs84["north"]),
                ]
            ),
            "geodesic": _const(False),
        },
    )


def _expression_graph(value: dict[str, Any]) -> dict[str, Any]:
    return {"result": "0", "values": {"0": value}}


def _fn(function_name: str, arguments: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "functionInvocationValue": {
            "functionName": function_name,
            "arguments": dict(arguments),
        }
    }


def _const(value: Any) -> dict[str, Any]:
    return {"constantValue": value}


def _raw_request_record(
    *,
    dataset_key: str,
    collection_id: str,
    window: GeeFetchWindow,
) -> dict[str, Any]:
    return {
        "dataset_key": dataset_key,
        "collection_id": collection_id,
        "start": window.start,
        "end": window.end,
        "endpoint": GEE_VALUE_COMPUTE_URL_TEMPLATE,
        "credential_values_embedded": False,
    }


def _blocked_fetch_result(
    *,
    status: str,
    blockers: list[str],
    project_id: str,
    bbox_wgs84: Mapping[str, float],
    prepared_at: str,
    raw_summary: Mapping[str, Any] | None = None,
    external_api_calls_made: bool = False,
) -> GeeFetchResult:
    cache_policy = gee_numeric_no_cache_policy()
    return GeeFetchResult(
        status=status,
        blocker_reasons=list(blockers),
        external_api_calls_made=external_api_calls_made,
        raw_summary={
            "provider": GEE_PROVIDER_ID,
            "project_id": project_id,
            "bbox_wgs84": dict(bbox_wgs84),
            "prepared_at": prepared_at,
            "status": status,
            "blocker_reasons": list(blockers),
            "cache_policy": cache_policy,
            "secret_value_embedded": False,
            "runtime_safety_truth": False,
            **dict(raw_summary or {}),
        },
        smap_summary={
            "dataset_family": "SMAP",
            "collection_id": "NASA/SMAP/SPL4SMGP/008",
            "status": status,
            "sm_surface_wetness": None,
            "sm_rootzone_wetness": None,
            "antecedent_wetness_percentile": None,
            "sample_count": 0,
            "samples": [],
            "cache_policy": cache_policy,
        },
        gpm_summary={
            "dataset_family": "GPM_IMERG",
            "collection_id": "NASA/GPM_L3/IMERG_V07",
            "status": status,
            "last_72h_mm": None,
            "last_24h_mm": None,
            "last_3h_mm": None,
            "sample_count": 0,
            "samples": [],
            "cache_policy": cache_policy,
        },
        smap_timeseries={
            "artifact_kind": "gee_soil_moisture_timeseries",
            "project_id": project_id,
            "layer_id": "soil-moisture",
            "generated_at": prepared_at,
            "status": status,
            "samples": [],
            "cache_policy": cache_policy,
            "blocker_reasons": list(blockers),
            "candidate_only": True,
            "runtime_safety_truth": False,
        },
        gpm_timeseries={
            "artifact_kind": "gee_antecedent_rain_timeseries",
            "project_id": project_id,
            "layer_id": "antecedent-rain",
            "generated_at": prepared_at,
            "status": status,
            "samples": [],
            "cache_policy": cache_policy,
            "blocker_reasons": list(blockers),
            "candidate_only": True,
            "runtime_safety_truth": False,
        },
    )


def _mapping_result(response: Any) -> dict[str, Any]:
    if isinstance(response, Mapping):
        result = response.get("result")
        if isinstance(result, Mapping):
            return dict(result)
        if isinstance(response.get("values"), Mapping):
            return dict(response["values"])
    return {}


def _first_number(mapping: Mapping[str, Any], *keys: str) -> float | None:
    for key in keys:
        value = mapping.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return float(value)
    for key, value in mapping.items():
        lower_key = str(key).lower()
        if any(candidate in lower_key for candidate in keys):
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                return float(value)
    return None


def _millis(value: str) -> int:
    return int(_parse_datetime(value).timestamp() * 1000)


def _parse_datetime(value: str) -> datetime:
    normalized = value.strip()
    if normalized.endswith("Z"):
        normalized = f"{normalized[:-1]}+00:00"
    if "T" not in normalized:
        normalized = f"{normalized}T00:00:00+00:00"
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _safe_error_payload(exc: urllib.error.HTTPError) -> dict[str, Any]:
    try:
        raw = exc.read()
        payload = _json_loads_bytes(raw)
    except Exception:
        payload = {"error": str(exc)}
    return {
        "payload": payload,
        "secret_value_embedded": False,
    }


def json_dumps_bytes(payload: Mapping[str, Any]) -> bytes:
    import json

    return json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def _json_loads_bytes(payload: bytes) -> dict[str, Any]:
    import json

    loaded = json.loads(payload.decode("utf-8"))
    return loaded if isinstance(loaded, dict) else {"value": loaded}


def _first_present_env_ref(
    active_env: Mapping[str, str],
    *env_names: str,
) -> str | None:
    for env_name in env_names:
        if str(active_env.get(env_name, "")).strip():
            return f"env:{env_name}"
    return None


def _truthy(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        description="Build a compact Scout GEE route feature package."
    )
    parser.add_argument("--gpx", required=True, help="Input GPX route path.")
    parser.add_argument(
        "--out",
        default="scout_gee_feature_package.json",
        help="Output scout_gee_feature_package.json path.",
    )
    parser.add_argument("--project-id", default="scout-route")
    parser.add_argument(
        "--prepared-at",
        default=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    )
    parser.add_argument(
        "--segment-length-m",
        type=float,
        default=DEFAULT_GEE_ROUTE_SEGMENT_LENGTH_M,
        help="Fixed route segment length; v0.1 accepts 100-250m.",
    )
    parser.add_argument(
        "--buffer-m",
        type=float,
        default=DEFAULT_GEE_ROUTE_BUFFER_M,
        help="Route corridor buffer proxy width in meters.",
    )
    parser.add_argument("--dataset-config", default=None)
    parser.add_argument("--route-risk-geojson", default=None)
    parser.add_argument(
        "--allow-live-fetch",
        action="store_true",
        help="Allow server-side GEE REST calls when credentials are ready.",
    )
    args = parser.parse_args(argv)
    package = write_scout_gee_feature_package(
        gpx_path=args.gpx,
        output_path=args.out,
        project_id=args.project_id,
        prepared_at=args.prepared_at,
        segment_length_m=args.segment_length_m,
        buffer_m=args.buffer_m,
        dataset_config_path=args.dataset_config,
        route_risk_geojson_path=args.route_risk_geojson,
        allow_live_fetch=args.allow_live_fetch,
    )
    print(
        json.dumps(
            {
                "output": args.out,
                "status": package["status"],
                "segment_count": package["counts"]["segment_count"],
                "external_api_calls_made": package["boundary"][
                    "external_api_calls_made"
                ],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
