from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
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
