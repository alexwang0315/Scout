"""Boundary-tagged hardware and mobile evidence artifacts for Scout AI OS."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

from pydantic import Field

from scout.schemas.base import NonEmptyStr, SchemaModel


HardwareEvidenceSourceKind = Literal[
    "mobile_sensor",
    "wearable_sensor",
    "gnss",
    "imu",
    "wheel",
    "host_probe",
    "manual_probe",
    "other",
]

SAFE_HARDWARE_EVIDENCE_BOUNDARY: dict[str, bool] = {
    "advisory_only": True,
    "not_safety_truth": True,
    "hardware_control_allowed": False,
    "hardware_control_performed": False,
    "provider_control_allowed": False,
    "outbound_send_allowed": False,
    "outbound_sent": False,
    "phase1_l0_l4_state_mutation_allowed": False,
    "phase1_l0_l4_state_mutated": False,
    "phase1_runtime_safety_truth": False,
    "phase1_runtime_mutated": False,
    "safety_api_mutation_allowed": False,
    "safety_api_called": False,
    "runtime_ingest_performed": False,
    "provider_values_are_scout_truth": False,
    "generated_runtime_code_install_allowed": False,
}

_FORBIDDEN_TRUE_KEYS = {
    key
    for key, value in SAFE_HARDWARE_EVIDENCE_BOUNDARY.items()
    if value is False and key not in {"advisory_only", "not_safety_truth"}
}


class HardwareEvidenceSample(SchemaModel):
    """One source sample captured before Scout runtime promotion."""

    sample_id: NonEmptyStr = Field(default_factory=lambda: f"sample-{uuid4()}")
    source_kind: HardwareEvidenceSourceKind
    captured_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    values: dict[str, Any] = Field(default_factory=dict)
    units: dict[str, str] = Field(default_factory=dict)
    quality: dict[str, Any] = Field(default_factory=dict)
    provenance: dict[str, Any] = Field(default_factory=dict)


class HardwareEvidenceArtifact(SchemaModel):
    """Smoke-attachable evidence that cannot promote values into runtime truth."""

    artifact_kind: Literal["scout_hardware_evidence.v0"] = "scout_hardware_evidence.v0"
    artifact_id: NonEmptyStr = Field(default_factory=lambda: f"hardware-evidence-{uuid4()}")
    produced_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    source: NonEmptyStr
    source_device_id: str | None = None
    samples: list[HardwareEvidenceSample]
    boundary: dict[str, bool] = Field(
        default_factory=lambda: dict(SAFE_HARDWARE_EVIDENCE_BOUNDARY)
    )
    notes: list[str] = Field(default_factory=list)

    def assert_safe_boundary(self) -> None:
        assert_safe_hardware_evidence_boundary(self.boundary)


def build_hardware_evidence(
    *,
    source: str,
    samples: list[HardwareEvidenceSample | dict[str, Any]],
    source_device_id: str | None = None,
    boundary_overrides: dict[str, bool] | None = None,
    notes: list[str] | None = None,
) -> HardwareEvidenceArtifact:
    """Build a Scout hardware evidence artifact with safe boundary metadata."""

    boundary = _safe_boundary(boundary_overrides)
    artifact = HardwareEvidenceArtifact(
        source=source,
        source_device_id=source_device_id,
        samples=[
            sample
            if isinstance(sample, HardwareEvidenceSample)
            else HardwareEvidenceSample.model_validate(sample)
            for sample in samples
        ],
        boundary=boundary,
        notes=list(notes or []),
    )
    artifact.assert_safe_boundary()
    return artifact


def load_hardware_evidence_samples(path: Path) -> list[HardwareEvidenceSample]:
    """Load one sample object or a sample list from JSON."""

    payload = json.loads(path.read_text(encoding="utf-8"))
    raw_samples: list[Any]
    if isinstance(payload, list):
        raw_samples = payload
    elif isinstance(payload, dict) and isinstance(payload.get("samples"), list):
        raw_samples = payload["samples"]
    elif isinstance(payload, dict):
        raw_samples = [payload]
    else:
        raise ValueError("sample JSON must be an object, a list, or contain samples")
    return [HardwareEvidenceSample.model_validate(sample) for sample in raw_samples]


def write_hardware_evidence(artifact: HardwareEvidenceArtifact, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(artifact.model_dump(mode="json"), indent=2, sort_keys=True),
        encoding="utf-8",
    )


def assert_safe_hardware_evidence_boundary(boundary: dict[str, Any]) -> None:
    forbidden_true = {
        key: value
        for key, value in boundary.items()
        if key in _FORBIDDEN_TRUE_KEYS and value is True
    }
    if forbidden_true:
        raise ValueError(
            "hardware evidence boundary cannot enable runtime effects: "
            f"{sorted(forbidden_true)}"
        )
    if boundary.get("advisory_only") is not True:
        raise ValueError("hardware evidence must keep advisory_only=true")
    if boundary.get("not_safety_truth") is not True:
        raise ValueError("hardware evidence must keep not_safety_truth=true")


def _safe_boundary(overrides: dict[str, bool] | None) -> dict[str, bool]:
    boundary = dict(SAFE_HARDWARE_EVIDENCE_BOUNDARY)
    boundary.update(overrides or {})
    assert_safe_hardware_evidence_boundary(boundary)
    return boundary


__all__ = [
    "HardwareEvidenceArtifact",
    "HardwareEvidenceSample",
    "HardwareEvidenceSourceKind",
    "SAFE_HARDWARE_EVIDENCE_BOUNDARY",
    "assert_safe_hardware_evidence_boundary",
    "build_hardware_evidence",
    "load_hardware_evidence_samples",
    "write_hardware_evidence",
]
