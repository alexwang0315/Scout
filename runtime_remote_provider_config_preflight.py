from __future__ import annotations

import json
from enum import StrEnum
from typing import Iterable, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from runtime_remote_provider_policy import (
    RuntimeRemoteMessageClass,
    RuntimeRemoteProviderKind,
    RuntimeRemoteProviderPolicyContract,
)


class RuntimeRemoteProviderConfigModel(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class RuntimeRemoteProviderConfigPreflightStatus(StrEnum):
    READY = "provider_config_ready"
    BLOCKED = "provider_config_blocked"


class RuntimeRemoteProviderEndpointConfig(RuntimeRemoteProviderConfigModel):
    endpoint_ref: str = Field(min_length=1)
    endpoint_url_secret_ref: str = Field(min_length=1)
    raw_url_embedded: Literal[False] = False


class RuntimeRemoteProviderAuthConfig(RuntimeRemoteProviderConfigModel):
    auth_secret_ref: str = Field(min_length=1)
    signature_secret_ref: str | None = None
    token_value_embedded: Literal[False] = False
    secret_values_loaded: Literal[False] = False


class RuntimeRemoteRecipientBinding(RuntimeRemoteProviderConfigModel):
    recipient_ref: str = Field(min_length=1)
    delivery_target_secret_ref: str = Field(min_length=1)
    raw_delivery_target_embedded: Literal[False] = False


class RuntimeRemoteProviderConfigBoundary(RuntimeRemoteProviderConfigModel):
    config_only: Literal[True] = True
    creates_provider_adapter: Literal[False] = False
    sends_network_request: Literal[False] = False
    sends_real_remote_notification: Literal[False] = False
    enables_phase1_incident_bridge: Literal[False] = False
    writes_phase2_brain: Literal[False] = False


class RuntimeRemoteProviderConfig(RuntimeRemoteProviderConfigModel):
    artifact_kind: Literal["runtime_remote_provider_config"] = (
        "runtime_remote_provider_config"
    )
    status: Literal["config_template_not_connected"] = "config_template_not_connected"
    provider_id: str = Field(min_length=1)
    provider_kind: RuntimeRemoteProviderKind
    endpoint: RuntimeRemoteProviderEndpointConfig
    auth: RuntimeRemoteProviderAuthConfig
    recipients: list[RuntimeRemoteRecipientBinding] = Field(min_length=1)
    enabled_message_classes: list[RuntimeRemoteMessageClass] = Field(min_length=1)
    boundary: RuntimeRemoteProviderConfigBoundary = Field(
        default_factory=RuntimeRemoteProviderConfigBoundary
    )

    @model_validator(mode="after")
    def enforce_config_boundary(self) -> "RuntimeRemoteProviderConfig":
        if self.endpoint.raw_url_embedded:
            raise ValueError("remote provider config must not embed a raw endpoint URL")
        if self.auth.token_value_embedded:
            raise ValueError("remote provider config must not embed token values")
        if self.auth.secret_values_loaded:
            raise ValueError("remote provider config must not load secret values")
        if self.boundary.sends_network_request:
            raise ValueError("remote provider config must not send network requests")
        return self

    def required_secret_refs(self) -> list[str]:
        refs = [
            self.endpoint.endpoint_url_secret_ref,
            self.auth.auth_secret_ref,
        ]
        if self.auth.signature_secret_ref:
            refs.append(self.auth.signature_secret_ref)
        refs.extend(
            recipient.delivery_target_secret_ref for recipient in self.recipients
        )
        return refs

    def to_json(self) -> str:
        return json.dumps(
            self.model_dump(mode="json"), ensure_ascii=False, indent=2, sort_keys=True
        ) + "\n"


class RuntimeRemoteProviderConfigPreflightReport(RuntimeRemoteProviderConfigModel):
    artifact_kind: Literal["runtime_remote_provider_config_preflight_report"] = (
        "runtime_remote_provider_config_preflight_report"
    )
    status: RuntimeRemoteProviderConfigPreflightStatus
    provider_config_ready: bool
    provider_id: str
    provider_kind: RuntimeRemoteProviderKind
    endpoint_ref: str
    required_secret_refs: list[str] = Field(default_factory=list)
    missing_secret_refs: list[str] = Field(default_factory=list)
    available_secret_ref_count: int = 0
    blocker_count: int = 0
    blocker_reasons: list[str] = Field(default_factory=list)
    secret_values_loaded: Literal[False] = False
    endpoint_url_embedded: Literal[False] = False
    token_value_embedded: Literal[False] = False
    send_performed: Literal[False] = False
    remote_notification_send_count: Literal[0] = 0
    incident_bridge_enable_count: Literal[0] = 0
    phase2_writeback_count: Literal[0] = 0


def build_webhook_remote_provider_config_template(
    policy: RuntimeRemoteProviderPolicyContract,
) -> RuntimeRemoteProviderConfig:
    return RuntimeRemoteProviderConfig(
        provider_id=policy.provider_id,
        provider_kind=policy.provider_kind,
        endpoint=RuntimeRemoteProviderEndpointConfig(
            endpoint_ref=policy.endpoint.endpoint_ref,
            endpoint_url_secret_ref="env:SCOUT_REMOTE_WEBHOOK_URL",
        ),
        auth=RuntimeRemoteProviderAuthConfig(
            auth_secret_ref="env:SCOUT_REMOTE_WEBHOOK_TOKEN",
            signature_secret_ref="env:SCOUT_REMOTE_WEBHOOK_HMAC_SECRET",
        ),
        recipients=[
            RuntimeRemoteRecipientBinding(
                recipient_ref="remote_contact.primary",
                delivery_target_secret_ref="env:SCOUT_REMOTE_PRIMARY_TARGET_REF",
            ),
            RuntimeRemoteRecipientBinding(
                recipient_ref="remote_contact.backup",
                delivery_target_secret_ref="env:SCOUT_REMOTE_BACKUP_TARGET_REF",
            ),
        ],
        enabled_message_classes=list(policy.message_classes.allowed_message_classes),
    )


def run_runtime_remote_provider_config_preflight(
    policy: RuntimeRemoteProviderPolicyContract,
    config: RuntimeRemoteProviderConfig,
    *,
    available_secret_refs: Iterable[str] | None = None,
) -> RuntimeRemoteProviderConfigPreflightReport:
    available_refs = set(available_secret_refs or [])
    required_refs = config.required_secret_refs()
    missing_refs = [ref for ref in required_refs if ref not in available_refs]
    blockers: list[str] = []

    if config.provider_id != policy.provider_id:
        blockers.append("provider_id_mismatch")
    if config.provider_kind != policy.provider_kind:
        blockers.append("provider_kind_mismatch")
    if config.endpoint.endpoint_ref != policy.endpoint.endpoint_ref:
        blockers.append("endpoint_ref_mismatch")
    if missing_refs:
        blockers.append("missing_secret_refs")
    if config.endpoint.raw_url_embedded:
        blockers.append("raw_endpoint_url_embedded")
    if config.auth.token_value_embedded:
        blockers.append("token_value_embedded")
    if config.auth.secret_values_loaded:
        blockers.append("secret_values_loaded")

    allowed_message_classes = set(policy.message_classes.allowed_message_classes)
    for message_class in config.enabled_message_classes:
        if message_class not in allowed_message_classes:
            blockers.append(f"message_class_not_allowed:{message_class.value}")

    allowed_recipients = set(policy.recipients.allowed_recipient_refs)
    for recipient in config.recipients:
        if recipient.recipient_ref not in allowed_recipients:
            blockers.append(f"recipient_ref_not_allowed:{recipient.recipient_ref}")
        if recipient.raw_delivery_target_embedded:
            blockers.append(f"raw_delivery_target_embedded:{recipient.recipient_ref}")

    if not config.boundary.config_only:
        blockers.append("config_boundary_not_config_only")
    if config.boundary.creates_provider_adapter:
        blockers.append("config_creates_provider_adapter")
    if config.boundary.sends_network_request:
        blockers.append("config_sends_network_request")
    if config.boundary.sends_real_remote_notification:
        blockers.append("config_sends_real_remote_notification")
    if config.boundary.enables_phase1_incident_bridge:
        blockers.append("config_enables_phase1_incident_bridge")
    if config.boundary.writes_phase2_brain:
        blockers.append("config_writes_phase2_brain")

    ready = not blockers
    return RuntimeRemoteProviderConfigPreflightReport(
        status=(
            RuntimeRemoteProviderConfigPreflightStatus.READY
            if ready
            else RuntimeRemoteProviderConfigPreflightStatus.BLOCKED
        ),
        provider_config_ready=ready,
        provider_id=config.provider_id,
        provider_kind=config.provider_kind,
        endpoint_ref=config.endpoint.endpoint_ref,
        required_secret_refs=required_refs,
        missing_secret_refs=missing_refs,
        available_secret_ref_count=len([ref for ref in required_refs if ref in available_refs]),
        blocker_count=len(blockers),
        blocker_reasons=blockers,
    )
