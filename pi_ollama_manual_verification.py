from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


SECRET_LIKE_MARKERS = (
    "sk-",
    "Bearer ",
    "OPENROUTER_API_KEY=",
    "token-value",
    "api_key=",
)


class PiOllamaAssistantStatusObservation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    local_fallback_mode: Literal["pi_field_manual_opt_in"]
    manual_verification_required: Literal[True]
    local_fallback_max_concurrency: Literal[1]
    readiness_starts_local_model: Literal[False]
    local_model_listener_required_for_readiness: Literal[False]
    status_model_switch_allowed: Literal[False]
    token_values_exposed: Literal[False]


class PiOllamaAssistantResponseObservation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model_profile_used: Literal["local"]
    failover_reason: str = Field(min_length=1, max_length=200)
    read_only: Literal[True]
    model_interpretation: Literal[True]


class PiOllamaBoundaryObservation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    phase1_state_changed: Literal[False]
    observed_fact_written: Literal[False]
    phase2_brain_written: Literal[False]
    incident_store_written: Literal[False]
    review_decision_changed: Literal[False]
    outbound_sent: Literal[False]
    hardware_controlled: Literal[False]


class PiOllamaManualVerificationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_type: Literal["manual_only_pi_ollama_verification"]
    timestamp: datetime
    runtime_profile: Literal["pi-field"]
    assistant_provider: Literal["pydantic_ai"]
    config_path_ref: str = Field(min_length=1, max_length=500)
    fallback_to_local_on_error: Literal[True]
    ollama_tags_checked: Literal[True]
    local_model_name: str = Field(min_length=1, max_length=100)
    operator_observed_latency_ms: int = Field(ge=0, le=300000)
    assistant_status: PiOllamaAssistantStatusObservation
    assistant_response: PiOllamaAssistantResponseObservation
    boundary_observation: PiOllamaBoundaryObservation

    @model_validator(mode="after")
    def reject_secret_like_values(self) -> "PiOllamaManualVerificationResult":
        for value in _walk_strings(self.model_dump(mode="json")):
            if any(marker in value for marker in SECRET_LIKE_MARKERS):
                raise ValueError("manual verification result contains a secret-like value")
        return self


class PiOllamaManualVerificationIndexEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    summary_ref: str = Field(min_length=1, max_length=120)
    fixture_path: str = Field(min_length=1, max_length=300)
    timestamp: datetime
    runtime_profile: Literal["pi-field"]
    local_model_name: str = Field(min_length=1, max_length=100)
    operator_observed_latency_ms: int = Field(ge=0, le=300000)
    read_only: Literal[True]
    model_interpretation: Literal[True]
    phase1_state_changed: Literal[False]
    observed_fact_written: Literal[False]
    outbound_sent: Literal[False]
    hardware_controlled: Literal[False]

    @model_validator(mode="after")
    def validate_reference_only_entry(self) -> "PiOllamaManualVerificationIndexEntry":
        if self.fixture_path.startswith("/") or ".." in Path(self.fixture_path).parts:
            raise ValueError("manual verification index requires a repo-relative fixture path")
        if not self.fixture_path.startswith("tests/fixtures/hardware/"):
            raise ValueError("manual verification index requires a repo-relative fixture path")
        for value in _walk_strings(self.model_dump(mode="json")):
            if any(marker in value for marker in SECRET_LIKE_MARKERS):
                raise ValueError("manual verification index contains a secret-like value")
        return self


class PiOllamaManualVerificationIndex(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_type: Literal["manual_only_pi_ollama_verification_index"]
    index_version: Literal[1]
    generated_by: Literal["operator_recorded_manual_index"]
    entries: list[PiOllamaManualVerificationIndexEntry] = Field(min_length=1, max_length=100)


def load_pi_ollama_manual_verification_result(
    path: Path | str,
) -> PiOllamaManualVerificationResult:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return PiOllamaManualVerificationResult.model_validate(payload)


def load_pi_ollama_manual_verification_index(
    path: Path | str,
) -> PiOllamaManualVerificationIndex:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return PiOllamaManualVerificationIndex.model_validate(payload)


def format_pi_ollama_manual_verification_summary(
    result: PiOllamaManualVerificationResult,
) -> str:
    status = result.assistant_status
    response = result.assistant_response
    boundary = result.boundary_observation
    lines = [
        "Manual Pi/Ollama verification summary",
        "Scope: optional operator-recorded fixture; not part of the assistant readiness gate.",
        "Boundary: read-only model interpretation; no Scout state writes.",
        f"timestamp={result.timestamp.isoformat()}",
        f"runtime_profile={result.runtime_profile}",
        f"assistant_provider={result.assistant_provider}",
        f"local_model_name={result.local_model_name}",
        f"operator_observed_latency_ms={result.operator_observed_latency_ms}",
        f"local_fallback_mode={status.local_fallback_mode}",
        f"manual_verification_required={_bool_text(status.manual_verification_required)}",
        f"local_fallback_max_concurrency={status.local_fallback_max_concurrency}",
        f"readiness_starts_local_model={_bool_text(status.readiness_starts_local_model)}",
        (
            "local_model_listener_required_for_readiness="
            f"{_bool_text(status.local_model_listener_required_for_readiness)}"
        ),
        f"status_model_switch_allowed={_bool_text(status.status_model_switch_allowed)}",
        f"token_values_exposed={_bool_text(status.token_values_exposed)}",
        f"model_profile_used={response.model_profile_used}",
        f"failover_reason={response.failover_reason}",
        f"read_only={_bool_text(response.read_only)}",
        f"model_interpretation={_bool_text(response.model_interpretation)}",
        f"phase1_state_changed={_bool_text(boundary.phase1_state_changed)}",
        f"observed_fact_written={_bool_text(boundary.observed_fact_written)}",
        f"phase2_brain_written={_bool_text(boundary.phase2_brain_written)}",
        f"incident_store_written={_bool_text(boundary.incident_store_written)}",
        f"review_decision_changed={_bool_text(boundary.review_decision_changed)}",
        f"outbound_sent={_bool_text(boundary.outbound_sent)}",
        f"hardware_controlled={_bool_text(boundary.hardware_controlled)}",
    ]
    return "\n".join(lines)


def summarize_pi_ollama_manual_verification_index(
    index: PiOllamaManualVerificationIndex,
) -> str:
    lines = [
        "Manual Pi/Ollama verification index summary",
        "Scope: optional append-only index; not part of the assistant readiness gate.",
        f"artifact_type={index.artifact_type}",
        f"index_version={index.index_version}",
        f"entry_count={len(index.entries)}",
    ]
    for entry in index.entries:
        lines.extend(
            [
                f"summary_ref={entry.summary_ref}",
                f"fixture_path={entry.fixture_path}",
                f"timestamp={entry.timestamp.isoformat()}",
                f"runtime_profile={entry.runtime_profile}",
                f"local_model_name={entry.local_model_name}",
                f"operator_observed_latency_ms={entry.operator_observed_latency_ms}",
                f"read_only={_bool_text(entry.read_only)}",
                f"model_interpretation={_bool_text(entry.model_interpretation)}",
                f"phase1_state_changed={_bool_text(entry.phase1_state_changed)}",
                f"observed_fact_written={_bool_text(entry.observed_fact_written)}",
                f"outbound_sent={_bool_text(entry.outbound_sent)}",
                f"hardware_controlled={_bool_text(entry.hardware_controlled)}",
            ]
        )
    return "\n".join(lines)


def _walk_strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        strings: list[str] = []
        for child in value.values():
            strings.extend(_walk_strings(child))
        return strings
    if isinstance(value, list):
        strings = []
        for child in value:
            strings.extend(_walk_strings(child))
        return strings
    return []


def _bool_text(value: bool) -> str:
    return "true" if value else "false"
