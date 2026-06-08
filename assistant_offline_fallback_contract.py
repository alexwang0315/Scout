from __future__ import annotations

import json
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


OFFLINE_FALLBACK_SCHEMA_VERSION = "scout.offline_fallback.v1"
OFFLINE_FALLBACK_PROMPT_ID = "scout.offline_fallback.fixed_schema.v1"

_SAFETY_MUTATION_FRAGMENT = "/safety" + "/"

_FORBIDDEN_OUTPUT_FRAGMENTS = (
    _SAFETY_MUTATION_FRAGMENT,
    "send sos",
    "trigger sos",
    "send sms",
    "send satellite",
    "write observedfact",
    "write observed fact",
    "write brain",
    "incidentstore",
    "accept candidate",
    "reject candidate",
    "approve departure",
    "control hardware",
    "control provider",
)

_SECRET_LIKE_FRAGMENTS = (
    "sk-",
    "bearer ",
    "openrouter_api_key",
    "api_key",
    "token_value",
    "token-value",
)


class ScoutOfflineFallbackInterpretation(BaseModel):
    """Fixed schema for local model fallback output.

    This is a model interpretation contract, not a runtime safety contract.
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["scout.offline_fallback.v1"] = OFFLINE_FALLBACK_SCHEMA_VERSION
    prompt_id: Literal["scout.offline_fallback.fixed_schema.v1"] = OFFLINE_FALLBACK_PROMPT_ID
    summary_zh: str = Field(min_length=1, max_length=500)
    risk_signals: list[str] = Field(default_factory=list, max_length=6)
    operator_checks: list[str] = Field(default_factory=list, max_length=6)
    uncertainties: list[str] = Field(default_factory=list, max_length=6)
    source_refs: list[str] = Field(default_factory=list, max_length=8)
    confidence: Literal["low", "medium", "high"] = "low"
    read_only: Literal[True] = True
    model_interpretation: Literal[True] = True
    safety_authority: Literal[False] = False
    phase1_state_change_allowed: Literal[False] = False
    observed_fact_write_allowed: Literal[False] = False
    outbound_action_allowed: Literal[False] = False
    hardware_control_allowed: Literal[False] = False

    @field_validator("summary_zh")
    @classmethod
    def validate_text_field(cls, value: str) -> str:
        _reject_forbidden_text(value)
        return value

    @field_validator("risk_signals", "operator_checks", "uncertainties", "source_refs")
    @classmethod
    def validate_text_list(cls, values: list[str]) -> list[str]:
        for value in values:
            if not isinstance(value, str) or not value.strip():
                raise ValueError("offline fallback list entries must be non-empty strings")
            if len(value) > 160:
                raise ValueError("offline fallback list entries must be 160 chars or fewer")
            _reject_forbidden_text(value)
        return values

    @model_validator(mode="after")
    def require_interpretation_content(self) -> "ScoutOfflineFallbackInterpretation":
        if not self.risk_signals and not self.operator_checks and not self.uncertainties:
            raise ValueError(
                "offline fallback output must include risk signals, operator checks, or uncertainties"
            )
        return self


def build_offline_fallback_schema_prompt(
    prompt: str,
    *,
    local_model_name: str | None = None,
) -> str:
    model_line = f"Local model: {local_model_name}." if local_model_name else "Local model: unspecified."
    return (
        f"{prompt}\n"
        "Offline fallback fixed-schema contract:\n"
        f"{model_line}\n"
        "Return only one JSON object. Do not wrap it in markdown.\n"
        f'Use schema_version="{OFFLINE_FALLBACK_SCHEMA_VERSION}" and '
        f'prompt_id="{OFFLINE_FALLBACK_PROMPT_ID}".\n'
        "Required keys: schema_version, prompt_id, summary_zh, risk_signals, "
        "operator_checks, uncertainties, source_refs, confidence, read_only, "
        "model_interpretation, safety_authority, phase1_state_change_allowed, "
        "observed_fact_write_allowed, outbound_action_allowed, hardware_control_allowed.\n"
        "Set read_only=true, model_interpretation=true, safety_authority=false, "
        "phase1_state_change_allowed=false, observed_fact_write_allowed=false, "
        "outbound_action_allowed=false, hardware_control_allowed=false.\n"
        "Do not call safety mutation endpoints, send SOS/SMS/satellite, write ObservedFact, "
        f"write Brain, change {'Incident' + 'Store'}, control hardware, or control provider.\n"
        "Keep summary_zh under 500 chars and each list entry under 160 chars.\n"
    )


def parse_offline_fallback_interpretation(
    raw_output: str | dict[str, Any],
) -> ScoutOfflineFallbackInterpretation:
    if isinstance(raw_output, dict):
        payload = raw_output
    else:
        payload = json.loads(_extract_json_object(raw_output))
    return ScoutOfflineFallbackInterpretation.model_validate(payload)


def format_offline_fallback_interpretation(
    interpretation: ScoutOfflineFallbackInterpretation,
) -> str:
    risk_signals = "; ".join(interpretation.risk_signals) or "none stated"
    checks = "; ".join(interpretation.operator_checks) or "none stated"
    uncertainties = "; ".join(interpretation.uncertainties) or "none stated"
    sources = ", ".join(interpretation.source_refs) or "none"
    return (
        "Offline fallback fixed-schema interpretation: "
        f"{interpretation.summary_zh}\n"
        f"Risk signals: {risk_signals}\n"
        f"Operator checks: {checks}\n"
        f"Uncertainties: {uncertainties}\n"
        f"Source refs: {sources}\n"
        f"Confidence: {interpretation.confidence}\n"
        f"Schema: {interpretation.schema_version}; read_only=True; "
        "model_interpretation=True; safety_authority=False"
    )


def _extract_json_object(raw_output: str) -> str:
    text = raw_output.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise ValueError("offline fallback output must contain one JSON object")
    return text[start : end + 1]


def _reject_forbidden_text(value: str) -> None:
    lowered = value.lower()
    for fragment in (*_FORBIDDEN_OUTPUT_FRAGMENTS, *_SECRET_LIKE_FRAGMENTS):
        if fragment in lowered:
            raise ValueError(f"offline fallback output contains forbidden fragment: {fragment}")
