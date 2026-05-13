from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


SkillStatus = Literal["candidate", "experimental", "field_trial", "stable", "deprecated", "disabled"]
SkillType = Literal["check", "analysis", "summary", "artifact", "beacon"]
ActivationMode = Literal["automatic", "manual", "operator_approved", "disabled"]
FailureAction = Literal["record_failure", "defer", "degrade", "disable"]
AuditRetention = Literal["mission_lifetime", "incident_package", "short_term"]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SkillTrigger(StrictModel):
    event: str
    description: str
    required_refs: list[str] = Field(default_factory=list)


class ActivationGate(StrictModel):
    mode: ActivationMode
    requires_human_approval: bool = False
    conditions: list[str] = Field(default_factory=list)


class NoiseControl(StrictModel):
    cooldown_seconds: int = Field(default=0, ge=0)
    dedupe_window_seconds: int = Field(default=0, ge=0)
    max_runs_per_mission: int | None = Field(default=None, ge=1)
    suppression_keys: list[str] = Field(default_factory=list)


class PreflightPolicy(StrictModel):
    required_skill_ids: list[str] = Field(default_factory=list)
    required_capabilities: list[str] = Field(default_factory=list)
    required_artifacts: list[str] = Field(default_factory=list)


class OutputSchema(StrictModel):
    format: Literal["brain-node", "artifact", "status-json", "control-signal"]
    node_types: list[str] = Field(default_factory=list)
    artifact_kinds: list[str] = Field(default_factory=list)
    required_fields: list[str] = Field(default_factory=list)


class RetryPolicy(StrictModel):
    max_attempts: int = Field(default=0, ge=0)
    backoff_seconds: int = Field(default=0, ge=0)


class FailurePolicy(StrictModel):
    on_error: FailureAction
    retry: RetryPolicy = Field(default_factory=RetryPolicy)
    degrade_to: str | None = None


class ControlSurface(StrictModel):
    operator_visible: bool = True
    manual_run_allowed: bool = False
    disable_allowed: bool = True
    status_label: str


class AuditSettings(StrictModel):
    log_inputs: bool = True
    log_outputs: bool = True
    log_decision: bool = True
    retention: AuditRetention = "mission_lifetime"


class SkillManifest(StrictModel):
    id: str
    version: str
    status: SkillStatus
    type: SkillType
    priority: int = Field(ge=0, le=100)
    triggers: list[SkillTrigger] = Field(min_length=1)
    activation_gate: ActivationGate
    noise_control: NoiseControl
    preflight: PreflightPolicy
    allowed_reads: list[str] = Field(default_factory=list)
    allowed_writes: list[str] = Field(default_factory=list)
    forbidden_writes: list[str] = Field(default_factory=list)
    output_schema: OutputSchema
    failure_policy: FailurePolicy
    control_surface: ControlSurface
    audit: AuditSettings

    @model_validator(mode="after")
    def validate_write_boundaries(self) -> SkillManifest:
        overlapping_writes = set(self.allowed_writes) & set(self.forbidden_writes)
        if overlapping_writes:
            overlaps = ", ".join(sorted(overlapping_writes))
            raise ValueError(f"allowed_writes overlaps forbidden_writes: {overlaps}")
        return self
