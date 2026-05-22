from __future__ import annotations

import json
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from runtime_observation_envelope import RuntimeObservationEnvelope
from runtime_stream_policy import RuntimeStreamSourceKind


class RuntimeStreamDeviceIdentityModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RuntimeStreamDeviceIdentityStatus(StrEnum):
    ENABLED = "enabled"
    DISABLED = "disabled"


class RuntimeStreamDeviceCredentialRef(RuntimeStreamDeviceIdentityModel):
    credential_ref: str = Field(min_length=1)
    token_scope: Literal["runtime:observation:write"] = "runtime:observation:write"
    hmac_secret_ref: str = Field(min_length=1)
    signature_algorithm: Literal["hmac_sha256"] = "hmac_sha256"
    secret_value_embedded: Literal[False] = False

    @model_validator(mode="after")
    def enforce_secret_ref_only(self) -> "RuntimeStreamDeviceCredentialRef":
        forbidden_prefixes = ("secret:", "token:", "raw:")
        if self.hmac_secret_ref.startswith(forbidden_prefixes):
            raise ValueError("device identity must store a secret reference, not a secret value")
        return self


class RuntimeStreamDeviceIdentityBoundary(RuntimeStreamDeviceIdentityModel):
    identity_metadata_only: Literal[True] = True
    raw_payload_embedded: Literal[False] = False
    secret_values_embedded: Literal[False] = False
    calls_safety_api: Literal[False] = False
    controls_device_hardware: Literal[False] = False
    enables_incident_bridge: Literal[False] = False
    writes_phase2_brain: Literal[False] = False
    notes: list[str] = Field(
        default_factory=lambda: [
            "Runtime Stream Device Identity / 串流裝置身份 binds source_id, source_kind, device_id, and credential refs.",
            "Credential refs point to scoped token and HMAC material but never embed secret values.",
            "Identity checks do not call /safety, control device hardware, enable incident bridge, or write Phase 2.",
        ]
    )


class RuntimeStreamDeviceIdentity(RuntimeStreamDeviceIdentityModel):
    artifact_kind: Literal["runtime_stream_device_identity"] = (
        "runtime_stream_device_identity"
    )
    source_id: str = Field(min_length=1)
    source_kind: RuntimeStreamSourceKind
    device_id: str = Field(min_length=1)
    display_name: str = Field(min_length=1)
    credential: RuntimeStreamDeviceCredentialRef
    status: RuntimeStreamDeviceIdentityStatus = RuntimeStreamDeviceIdentityStatus.ENABLED
    boundary: RuntimeStreamDeviceIdentityBoundary = Field(
        default_factory=RuntimeStreamDeviceIdentityBoundary
    )

    @property
    def enabled(self) -> bool:
        return self.status == RuntimeStreamDeviceIdentityStatus.ENABLED

    def to_json(self) -> str:
        return json.dumps(
            self.model_dump(mode="json"), ensure_ascii=False, indent=2, sort_keys=True
        ) + "\n"


class RuntimeStreamDeviceRegistry(RuntimeStreamDeviceIdentityModel):
    artifact_kind: Literal["runtime_stream_device_registry"] = (
        "runtime_stream_device_registry"
    )
    registry_id: str = Field(min_length=1)
    identities: list[RuntimeStreamDeviceIdentity] = Field(default_factory=list)
    boundary: RuntimeStreamDeviceIdentityBoundary = Field(
        default_factory=RuntimeStreamDeviceIdentityBoundary
    )

    def find_identity(
        self,
        *,
        source_id: str,
        source_kind: RuntimeStreamSourceKind | str,
        device_id: str,
    ) -> RuntimeStreamDeviceIdentity | None:
        expected_kind = RuntimeStreamSourceKind(source_kind)
        for identity in self.identities:
            if (
                identity.source_id == source_id
                and identity.source_kind == expected_kind
                and identity.device_id == device_id
            ):
                return identity
        return None


class RuntimeStreamDeviceIdentityDecision(RuntimeStreamDeviceIdentityModel):
    matched: bool
    reason: str = Field(min_length=1)
    credential_ref: str | None = None
    token_scope: str | None = None
    signature_algorithm: str | None = None
    secret_value_exposed: Literal[False] = False


def check_runtime_stream_device_identity(
    registry: RuntimeStreamDeviceRegistry | None,
    envelope: RuntimeObservationEnvelope,
) -> RuntimeStreamDeviceIdentityDecision:
    if registry is None:
        return RuntimeStreamDeviceIdentityDecision(
            matched=True,
            reason="device_identity_registry_not_configured",
        )

    identity = registry.find_identity(
        source_id=envelope.source_id,
        source_kind=envelope.source_kind,
        device_id=envelope.device_id,
    )
    if identity is None:
        return RuntimeStreamDeviceIdentityDecision(
            matched=False,
            reason="device_identity_not_registered",
        )
    if not identity.enabled:
        return RuntimeStreamDeviceIdentityDecision(
            matched=False,
            reason="device_identity_disabled",
            credential_ref=identity.credential.credential_ref,
            token_scope=identity.credential.token_scope,
            signature_algorithm=identity.credential.signature_algorithm,
        )
    if identity.credential.token_scope != envelope.token_scope:
        return RuntimeStreamDeviceIdentityDecision(
            matched=False,
            reason="device_identity_token_scope_mismatch",
            credential_ref=identity.credential.credential_ref,
            token_scope=identity.credential.token_scope,
            signature_algorithm=identity.credential.signature_algorithm,
        )
    if identity.credential.signature_algorithm != envelope.signature_algorithm:
        return RuntimeStreamDeviceIdentityDecision(
            matched=False,
            reason="device_identity_signature_algorithm_mismatch",
            credential_ref=identity.credential.credential_ref,
            token_scope=identity.credential.token_scope,
            signature_algorithm=identity.credential.signature_algorithm,
        )
    return RuntimeStreamDeviceIdentityDecision(
        matched=True,
        reason="device_identity_matched",
        credential_ref=identity.credential.credential_ref,
        token_scope=identity.credential.token_scope,
        signature_algorithm=identity.credential.signature_algorithm,
    )
