from __future__ import annotations

import os
from pathlib import Path

from safety_api import SafetyObservationAdmissionConfig


def create_safety_observation_admission_config_from_env(
    environ: dict[str, str] | os._Environ[str],
) -> SafetyObservationAdmissionConfig | None:
    if not _is_true_like(environ.get("SCOUT_SAFETY_OBSERVATION_ADMISSION_ENABLED")):
        return None

    secret = (environ.get("SCOUT_SAFETY_OBSERVATION_ADMISSION_SECRET") or "").strip()
    secret_file = (
        environ.get("SCOUT_SAFETY_OBSERVATION_ADMISSION_SECRET_FILE") or ""
    ).strip()
    if not secret and secret_file:
        secret_path = Path(secret_file)
        if not secret_path.exists():
            raise ValueError(
                "SCOUT_SAFETY_OBSERVATION_ADMISSION_SECRET_FILE secret file not found"
            )
        secret = secret_path.read_text(encoding="utf-8").strip()

    if not secret:
        raise ValueError(
            "SCOUT_SAFETY_OBSERVATION_ADMISSION_SECRET is required when signed safety observation admission is enabled"
        )
    if len(secret) < 16:
        raise ValueError(
            "SCOUT_SAFETY_OBSERVATION_ADMISSION_SECRET must be at least 16 characters"
        )
    return SafetyObservationAdmissionConfig(secret_key=secret)


def _is_true_like(value: str | None) -> bool:
    return value is not None and value.strip().lower() in {"1", "true", "yes", "y", "on"}
