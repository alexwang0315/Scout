from __future__ import annotations

import os
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
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
