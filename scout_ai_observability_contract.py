from __future__ import annotations

import time
from typing import Any, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field, model_validator

SCOUT_AI_OBSERVABILITY_SCHEMA_VERSION = "scout_ai_observability.v1"
SCOUT_AI_OTLP_SCOPE_NAME = "scout.ai.telemetry"
SCOUT_AI_DEFAULT_SERVICE_NAME = "scout-ai"
SCOUT_AI_VALIDATOR_ID = (
    "scout_ai_observability_contract.ScoutAiIntentPayload"
    f"@{SCOUT_AI_OBSERVABILITY_SCHEMA_VERSION}"
)
SCOUT_AI_REQUIRED_TELEMETRY_FIELDS = (
    "intent",
    "actions",
    "outcome",
    "prompt_hash",
    "model_id",
    "token_count",
    "latency_ms",
    "sample_rate",
)

SENSITIVE_KEY_FRAGMENTS = (
    "api_key",
    "auth",
    "bearer",
    "credential",
    "password",
    "private_key",
    "secret",
    "session",
    "token",
)

TScoutAiModel = TypeVar("TScoutAiModel", bound=BaseModel)


class ScoutAiObservabilityModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ScoutAiTelemetryAction(ScoutAiObservabilityModel):
    name: str = Field(min_length=1, max_length=128)
    params: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def reject_secret_like_params(self) -> "ScoutAiTelemetryAction":
        _reject_secret_like_keys(self.params, path="params")
        return self


class ScoutAiIntentPayload(ScoutAiObservabilityModel):
    schema_version: Literal["scout_ai_observability.v1"] = (
        SCOUT_AI_OBSERVABILITY_SCHEMA_VERSION
    )
    intent: str = Field(
        min_length=1,
        max_length=128,
        examples=["plan.hike.segment_risk", "nav.cp_eta_notify"],
    )
    actions: list[ScoutAiTelemetryAction] = Field(default_factory=list, max_length=32)
    outcome: Literal["success", "partial", "failure"] = Field(
        default="success",
        examples=["success", "partial", "failure"],
    )
    prompt_hash: str = Field(
        min_length=8,
        max_length=128,
        pattern=r"^[A-Za-z0-9._:-]+$",
        description="Irreversible hash of the upstream prompt or instruction.",
    )
    model_id: str = Field(min_length=1, max_length=128, examples=["openai/gpt-4o-mini"])
    token_count: int = Field(default=0, ge=0)
    latency_ms: int = Field(default=0, ge=0)
    sample_rate: float = Field(default=1.0, ge=0.0, le=1.0)


class ScoutAiProvenance(ScoutAiObservabilityModel):
    prompt_hash: str = Field(min_length=8, max_length=128, pattern=r"^[A-Za-z0-9._:-]+$")
    model: str = Field(min_length=1, max_length=128)
    schema_version: Literal["scout_ai_observability.v1"] = (
        SCOUT_AI_OBSERVABILITY_SCHEMA_VERSION
    )
    runtime: str = Field(min_length=1, max_length=256)
    validator: str = Field(default=SCOUT_AI_VALIDATOR_ID, min_length=1, max_length=256)


class ScoutAiObservabilityBoundary(ScoutAiObservabilityModel):
    telemetry_only: Literal[True] = True
    runtime_safety_truth: Literal[False] = False
    safety_mutation_allowed: Literal[False] = False
    outbound_send_performed: Literal[False] = False
    hardware_control_performed: Literal[False] = False
    raw_prompt_embedded: Literal[False] = False
    raw_model_output_embedded: Literal[False] = False
    sensitive_payload_embedded: Literal[False] = False

    @model_validator(mode="after")
    def enforce_non_authoritative_boundary(self) -> "ScoutAiObservabilityBoundary":
        if self.telemetry_only is not True:
            raise ValueError("Scout AI observability must remain telemetry-only")
        if self.runtime_safety_truth:
            raise ValueError("Scout AI observability must not become runtime safety truth")
        if self.safety_mutation_allowed:
            raise ValueError("Scout AI observability must not mutate safety state")
        if self.outbound_send_performed:
            raise ValueError("Scout AI observability must not perform outbound sends")
        if self.hardware_control_performed:
            raise ValueError("Scout AI observability must not perform hardware control")
        if self.raw_prompt_embedded:
            raise ValueError("Scout AI observability must not embed raw prompts")
        if self.raw_model_output_embedded:
            raise ValueError("Scout AI observability must not embed raw model output")
        if self.sensitive_payload_embedded:
            raise ValueError("Scout AI observability must not embed sensitive payloads")
        return self


class ScoutAiTelemetryEnvelope(ScoutAiObservabilityModel):
    artifact_kind: Literal["scout_ai_observability_record"] = (
        "scout_ai_observability_record"
    )
    artifact_version: Literal["scout_ai_observability.v1"] = (
        SCOUT_AI_OBSERVABILITY_SCHEMA_VERSION
    )
    payload: ScoutAiIntentPayload
    provenance: ScoutAiProvenance
    boundary: ScoutAiObservabilityBoundary = Field(
        default_factory=ScoutAiObservabilityBoundary
    )


def validate_with_model(model: type[TScoutAiModel], data: dict[str, Any]) -> TScoutAiModel:
    return model.model_validate(data)


def build_provenance_for_intent(
    payload: ScoutAiIntentPayload,
    *,
    runtime: str,
    validator: str = SCOUT_AI_VALIDATOR_ID,
) -> ScoutAiProvenance:
    return ScoutAiProvenance(
        prompt_hash=payload.prompt_hash,
        model=payload.model_id,
        runtime=runtime,
        validator=validator,
    )


def build_telemetry_envelope(
    payload: ScoutAiIntentPayload,
    *,
    runtime: str,
    validator: str = SCOUT_AI_VALIDATOR_ID,
) -> ScoutAiTelemetryEnvelope:
    return ScoutAiTelemetryEnvelope(
        payload=payload,
        provenance=build_provenance_for_intent(
            payload,
            runtime=runtime,
            validator=validator,
        ),
    )


def intent_payload_to_otlp_log_record(
    payload: ScoutAiIntentPayload,
    *,
    provenance: ScoutAiProvenance | None = None,
    time_unix_nano: int | None = None,
    trace_id: str | None = None,
    span_id: str | None = None,
    service_name: str = SCOUT_AI_DEFAULT_SERVICE_NAME,
    service_version: str | None = None,
    deployment_environment: str | None = None,
) -> dict[str, Any]:
    provenance = provenance or build_provenance_for_intent(
        payload,
        runtime="unknown",
    )
    record_attributes = [
        _attribute("scout.schema_version", payload.schema_version),
        _attribute("scout.provenance.runtime", provenance.runtime),
        _attribute("scout.provenance.validator", provenance.validator),
        _attribute("scout.telemetry_only", True),
        _attribute("scout.runtime_safety_truth", False),
    ]
    if trace_id is not None:
        record_attributes.append(_attribute("trace_id", trace_id))
    if span_id is not None:
        record_attributes.append(_attribute("span_id", span_id))

    resource_attributes = [_attribute("service.name", service_name)]
    if service_version is not None:
        resource_attributes.append(_attribute("service.version", service_version))
    if deployment_environment is not None:
        resource_attributes.append(
            _attribute("deployment.environment", deployment_environment)
        )

    return {
        "resourceLogs": [
            {
                "resource": {"attributes": resource_attributes},
                "scopeLogs": [
                    {
                        "scope": {
                            "name": SCOUT_AI_OTLP_SCOPE_NAME,
                            "version": SCOUT_AI_OBSERVABILITY_SCHEMA_VERSION,
                        },
                        "logRecords": [
                            {
                                "timeUnixNano": str(
                                    time_unix_nano
                                    if time_unix_nano is not None
                                    else _now_unix_nano()
                                ),
                                "severityNumber": 9,
                                "severityText": "INFO",
                                "body": {
                                    "kvlistValue": {
                                        "values": _payload_kv_values(payload)
                                    }
                                },
                                "attributes": record_attributes,
                            }
                        ],
                    }
                ],
            }
        ]
    }


def _payload_kv_values(payload: ScoutAiIntentPayload) -> list[dict[str, Any]]:
    return [
        _kv("intent", payload.intent),
        _kv("actions", [action.name for action in payload.actions]),
        _kv("outcome", payload.outcome),
        _kv("prompt_hash", payload.prompt_hash),
        _kv("model_id", payload.model_id),
        _kv("token_count", payload.token_count),
        _kv("latency_ms", payload.latency_ms),
        _kv("sample_rate", payload.sample_rate),
    ]


def _kv(key: str, value: Any) -> dict[str, Any]:
    return {"key": key, "value": _otlp_value(value)}


def _attribute(key: str, value: Any) -> dict[str, Any]:
    return _kv(key, value)


def _otlp_value(value: Any) -> dict[str, Any]:
    if isinstance(value, bool):
        return {"boolValue": value}
    if isinstance(value, int) and not isinstance(value, bool):
        return {"intValue": str(value)}
    if isinstance(value, float):
        return {"doubleValue": value}
    if isinstance(value, list):
        return {"arrayValue": {"values": [_otlp_value(item) for item in value]}}
    return {"stringValue": str(value)}


def _now_unix_nano() -> int:
    return time.time_ns()


def _reject_secret_like_keys(value: Any, *, path: str) -> None:
    if isinstance(value, dict):
        for key, nested in value.items():
            normalized = str(key).lower()
            if any(fragment in normalized for fragment in SENSITIVE_KEY_FRAGMENTS):
                raise ValueError(
                    f"{path}.{key} is a secret-like key and cannot be embedded "
                    "in Scout AI observability action params"
                )
            _reject_secret_like_keys(nested, path=f"{path}.{key}")
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            _reject_secret_like_keys(nested, path=f"{path}[{index}]")


__all__ = [
    "SCOUT_AI_DEFAULT_SERVICE_NAME",
    "SCOUT_AI_OBSERVABILITY_SCHEMA_VERSION",
    "SCOUT_AI_OTLP_SCOPE_NAME",
    "SCOUT_AI_REQUIRED_TELEMETRY_FIELDS",
    "SCOUT_AI_VALIDATOR_ID",
    "ScoutAiIntentPayload",
    "ScoutAiObservabilityBoundary",
    "ScoutAiProvenance",
    "ScoutAiTelemetryAction",
    "ScoutAiTelemetryEnvelope",
    "build_provenance_for_intent",
    "build_telemetry_envelope",
    "intent_payload_to_otlp_log_record",
    "validate_with_model",
]
