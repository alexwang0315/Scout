from __future__ import annotations

import json
from enum import StrEnum
from pathlib import Path
from typing import Iterable, Literal, Mapping

from pydantic import BaseModel, ConfigDict, Field, model_validator

from assistant_model_config import AssistantModelConfig, load_assistant_model_config
from runtime_remote_provider_config_preflight import (
    build_webhook_remote_provider_config_template,
)
from runtime_remote_provider_policy import build_webhook_remote_provider_policy_contract


class LiveRuntimeEnablementModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class LiveRuntimeGate(StrEnum):
    RUNTIME_STREAM = "runtime_stream"
    REMOTE_PROVIDER_LIVE_SEND = "remote_provider_live_send"
    LOCAL_MODEL_OLLAMA_FALLBACK = "local_model_ollama_fallback"
    HARDWARE_PROVIDER_CONTROL = "hardware_provider_control"


class LiveRuntimeEnablementStatus(StrEnum):
    READY = "live_enablement_ready"
    BLOCKED = "live_enablement_blocked"


class HardwareProviderControlAction(StrEnum):
    READ_PROVIDER_STATUS = "read_provider_status"
    SET_DEVICE_MODE = "set_device_mode"
    SILENCE_LOCAL_ALERT = "silence_local_alert"
    RESTART_PROVIDER = "restart_provider"


class HardwareProviderControlPolicy(LiveRuntimeEnablementModel):
    artifact_kind: Literal["hardware_provider_control_policy"] = (
        "hardware_provider_control_policy"
    )
    policy_id: str = Field(min_length=1, pattern=r"^[A-Za-z0-9_.:-]+$")
    allowed_provider_refs: list[str] = Field(min_length=1)
    allowed_actions: list[HardwareProviderControlAction] = Field(min_length=1)
    operator_authorization_required: Literal[True] = True
    arbitrary_shell_allowed: Literal[False] = False
    safety_mutation_allowed: Literal[False] = False
    phase1_safety_decision_mutation_allowed: Literal[False] = False
    outbound_send_allowed: Literal[False] = False
    token_values_embedded: Literal[False] = False

    @model_validator(mode="after")
    def enforce_live_control_policy(self) -> "HardwareProviderControlPolicy":
        if self.arbitrary_shell_allowed:
            raise ValueError("hardware control policy must not allow arbitrary shell")
        if self.safety_mutation_allowed:
            raise ValueError("hardware control policy must not allow /safety mutation")
        if self.phase1_safety_decision_mutation_allowed:
            raise ValueError(
                "hardware control policy must not mutate Phase 1 safety decisions"
            )
        if self.outbound_send_allowed:
            raise ValueError("hardware control policy must not send outbound messages")
        if self.token_values_embedded:
            raise ValueError("hardware control policy must not embed token values")
        return self

    def to_json(self) -> str:
        return json.dumps(
            self.model_dump(mode="json"),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        ) + "\n"


class LiveRuntimeEnablementBoundary(LiveRuntimeEnablementModel):
    preflight_only: Literal[True] = True
    mutates_runtime: Literal[False] = False
    secret_values_embedded: Literal[False] = False
    network_send_performed: Literal[False] = False
    hardware_control_performed: Literal[False] = False
    phase1_safety_decision_mutated: Literal[False] = False
    phase2_writeback_performed: Literal[False] = False


class LiveRuntimeEnablementReport(LiveRuntimeEnablementModel):
    artifact_kind: Literal["live_runtime_enablement_report"] = (
        "live_runtime_enablement_report"
    )
    status: LiveRuntimeEnablementStatus
    ready: bool
    requested_gates: list[str]
    ready_gates: list[str] = Field(default_factory=list)
    blocked_gates: list[str] = Field(default_factory=list)
    blocker_reasons: list[str] = Field(default_factory=list)
    required_secret_refs: list[str] = Field(default_factory=list)
    missing_secret_refs: list[str] = Field(default_factory=list)
    env_overlay: dict[str, str] = Field(default_factory=dict)
    assistant_config_path: str | None = None
    assistant_config_loaded: bool = False
    assistant_config_error_type: str | None = None
    local_model_name: str | None = None
    local_model_base_url_configured: bool = False
    hardware_control_policy_path: str | None = None
    hardware_control_policy_id: str | None = None
    hardware_control_allowed_actions: list[str] = Field(default_factory=list)
    boundary: LiveRuntimeEnablementBoundary = Field(
        default_factory=LiveRuntimeEnablementBoundary
    )


def build_live_runtime_enablement_report(
    environ: Mapping[str, str],
    *,
    requested_gates: Iterable[LiveRuntimeGate] | None = None,
) -> LiveRuntimeEnablementReport:
    gates = list(requested_gates or [])
    if not gates:
        gates = list(LiveRuntimeGate)
    requested = sorted(gate.value for gate in gates)
    required_secret_refs: list[str] = []
    missing_secret_refs: list[str] = []
    blockers: list[str] = []
    blocked_gates: set[str] = set()
    ready_gates: set[str] = set()

    assistant_config: AssistantModelConfig | None = None
    assistant_config_path = environ.get("SCOUT_AI_ASSISTANT_CONFIG_PATH")
    assistant_config_loaded = False
    assistant_config_error_type: str | None = None
    local_model_name: str | None = None
    local_model_base_url_configured = False
    hardware_policy_path = environ.get("SCOUT_HARDWARE_PROVIDER_CONTROL_POLICY_PATH")
    hardware_policy_id: str | None = None
    hardware_allowed_actions: list[str] = []

    for gate in gates:
        gate_blockers: list[str] = []
        if gate == LiveRuntimeGate.RUNTIME_STREAM:
            refs = _runtime_stream_secret_refs(environ)
            required_secret_refs.extend(refs)
            missing = [ref for ref in refs if not _secret_ref_available(ref, environ)]
            missing_secret_refs.extend(missing)
            if missing:
                gate_blockers.append("missing_runtime_stream_admission_secret")
        elif gate == LiveRuntimeGate.REMOTE_PROVIDER_LIVE_SEND:
            refs = _remote_provider_required_secret_refs(environ)
            required_secret_refs.extend(refs)
            missing = [ref for ref in refs if not _secret_ref_available(ref, environ)]
            missing_secret_refs.extend(missing)
            if missing:
                gate_blockers.append("missing_remote_provider_secret_refs")
        elif gate == LiveRuntimeGate.LOCAL_MODEL_OLLAMA_FALLBACK:
            if not assistant_config_path:
                gate_blockers.append("missing_assistant_model_config")
            else:
                try:
                    assistant_config = load_assistant_model_config(assistant_config_path)
                    assistant_config_loaded = True
                    local_model_name = assistant_config.local_model.model_name
                    local_model_base_url_configured = bool(
                        assistant_config.local_model.base_url
                    )
                    model_refs = _assistant_model_secret_refs(assistant_config)
                    required_secret_refs.extend(model_refs)
                    missing = [
                        ref for ref in model_refs if not _secret_ref_available(ref, environ)
                    ]
                    missing_secret_refs.extend(missing)
                    if not assistant_config.fallback_to_local_on_error:
                        gate_blockers.append("assistant_local_fallback_disabled")
                    if not assistant_config.local_fallback_fixed_schema:
                        gate_blockers.append("assistant_local_fixed_schema_disabled")
                    if not local_model_base_url_configured:
                        gate_blockers.append("missing_local_model_base_url")
                    if missing:
                        gate_blockers.append("missing_assistant_model_secret_refs")
                except Exception as exc:
                    assistant_config_error_type = type(exc).__name__
                    gate_blockers.append("assistant_model_config_invalid")
        elif gate == LiveRuntimeGate.HARDWARE_PROVIDER_CONTROL:
            control_token_refs = _hardware_control_token_refs(environ)
            required_secret_refs.extend(control_token_refs)
            missing = [
                ref for ref in control_token_refs if not _secret_ref_available(ref, environ)
            ]
            missing_secret_refs.extend(missing)
            if missing:
                gate_blockers.append("missing_hardware_control_token")
            if not hardware_policy_path:
                gate_blockers.append("missing_hardware_control_policy")
            else:
                try:
                    policy = load_hardware_provider_control_policy(hardware_policy_path)
                    hardware_policy_id = policy.policy_id
                    hardware_allowed_actions = [
                        action.value for action in policy.allowed_actions
                    ]
                except Exception as exc:
                    gate_blockers.append(f"hardware_control_policy_invalid:{type(exc).__name__}")
        if gate_blockers:
            blockers.extend(gate_blockers)
            blocked_gates.add(gate.value)
        else:
            ready_gates.add(gate.value)

    blockers = list(dict.fromkeys(blockers))
    required_secret_refs = sorted(set(required_secret_refs))
    missing_secret_refs = sorted(set(missing_secret_refs))
    ready = not blockers

    return LiveRuntimeEnablementReport(
        status=(
            LiveRuntimeEnablementStatus.READY
            if ready
            else LiveRuntimeEnablementStatus.BLOCKED
        ),
        ready=ready,
        requested_gates=requested,
        ready_gates=sorted(ready_gates),
        blocked_gates=sorted(blocked_gates),
        blocker_reasons=blockers,
        required_secret_refs=required_secret_refs,
        missing_secret_refs=missing_secret_refs,
        env_overlay=_env_overlay(gates),
        assistant_config_path=assistant_config_path,
        assistant_config_loaded=assistant_config_loaded,
        assistant_config_error_type=assistant_config_error_type,
        local_model_name=local_model_name,
        local_model_base_url_configured=local_model_base_url_configured,
        hardware_control_policy_path=hardware_policy_path,
        hardware_control_policy_id=hardware_policy_id,
        hardware_control_allowed_actions=hardware_allowed_actions,
    )


def load_hardware_provider_control_policy(
    path: Path | str,
) -> HardwareProviderControlPolicy:
    return HardwareProviderControlPolicy.model_validate_json(
        Path(path).expanduser().read_text(encoding="utf-8")
    )


def _runtime_stream_secret_refs(environ: Mapping[str, str]) -> list[str]:
    if environ.get("SCOUT_SAFETY_OBSERVATION_ADMISSION_SECRET_FILE"):
        return [f"file:{environ['SCOUT_SAFETY_OBSERVATION_ADMISSION_SECRET_FILE']}"]
    return ["env:SCOUT_SAFETY_OBSERVATION_ADMISSION_SECRET"]


def _hardware_control_token_refs(environ: Mapping[str, str]) -> list[str]:
    if environ.get("SCOUT_HARDWARE_PROVIDER_CONTROL_TOKEN_FILE"):
        return [f"file:{environ['SCOUT_HARDWARE_PROVIDER_CONTROL_TOKEN_FILE']}"]
    return ["env:SCOUT_HARDWARE_PROVIDER_CONTROL_TOKEN"]


def _remote_provider_required_secret_refs(environ: Mapping[str, str]) -> list[str]:
    if environ.get("SCOUT_REMOTE_PROVIDER_KIND", "").strip().lower() == "telegram_bot":
        return [
            "env:SCOUT_TELEGRAM_BOT_TOKEN",
            "env:SCOUT_TELEGRAM_TARGET_CHAT_ID",
        ]
    policy = build_webhook_remote_provider_policy_contract()
    config = build_webhook_remote_provider_config_template(policy)
    return config.required_secret_refs()


def _assistant_model_secret_refs(config: AssistantModelConfig) -> list[str]:
    refs: list[str] = []
    for profile in (config.cloud_model, config.local_model):
        if profile.token_env_var:
            refs.append(f"env:{profile.token_env_var}")
    return refs


def _secret_ref_available(secret_ref: str, environ: Mapping[str, str]) -> bool:
    scheme, _, ref = secret_ref.partition(":")
    if scheme == "env":
        return bool(environ.get(ref))
    if scheme == "file":
        return Path(ref).expanduser().exists()
    if scheme == "keychain":
        return True
    return False


def _env_overlay(gates: Iterable[LiveRuntimeGate]) -> dict[str, str]:
    gate_set = set(gates)
    overlay = {
        "SCOUT_RUNTIME_PROFILE": "pi-field-live",
        "SCOUT_ENABLE_LIVE_RUNTIME": "1",
    }
    if LiveRuntimeGate.RUNTIME_STREAM in gate_set:
        overlay.update(
            {
                "SCOUT_RUNTIME_STREAM_STATUS_ENABLED": "1",
                "SCOUT_SAFETY_OBSERVATION_ADMISSION_ENABLED": "1",
            }
        )
    if LiveRuntimeGate.REMOTE_PROVIDER_LIVE_SEND in gate_set:
        overlay["SCOUT_REMOTE_PROVIDER_LIVE_SEND_ENABLED"] = "1"
    if LiveRuntimeGate.LOCAL_MODEL_OLLAMA_FALLBACK in gate_set:
        overlay.update(
            {
                "SCOUT_AI_ASSISTANT_ENABLED": "1",
                "SCOUT_AI_ASSISTANT_PROVIDER": "pydantic_ai",
                "SCOUT_ENABLE_AI_INFERENCE": "1",
                "SCOUT_ENABLE_LOCAL_MODEL": "1",
            }
        )
    if LiveRuntimeGate.HARDWARE_PROVIDER_CONTROL in gate_set:
        overlay.update(
            {
                "SCOUT_ENABLE_LIVE_HARDWARE": "1",
                "SCOUT_HARDWARE_PROVIDER_CONTROL_ENABLED": "1",
            }
        )
    return overlay
