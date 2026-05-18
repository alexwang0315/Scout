from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class AssistantSurface(str, Enum):
    DEBUG = "debug"
    ADMIN = "admin"
    PRETRIP = "pretrip"
    HARDWARE_READINESS = "hardware_readiness"


class AssistantSurfaceConstraint(str, Enum):
    DEBUG_READ_ONLY = "debug_read_only"
    ADMIN_AFTER_ACTION_READ_ONLY = "admin_after_action_read_only"
    PRETRIP_READ_ONLY = "pretrip_read_only"
    HARDWARE_READINESS_READ_ONLY = "hardware_readiness_read_only"


class AssistantSourceRef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_id: str = Field(min_length=1)
    source_path: str | None = None
    evidence_type: str | None = None
    selected: bool = False
    context_summary: dict[str, Any] | None = None


class AssistantBoundary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    surface: AssistantSurface
    read_only: Literal[True] = True
    model_interpretation: Literal[True] = True
    phase1_mutation_allowed: Literal[False] = False
    safety_mutation_allowed: Literal[False] = False
    phase2_writeback_allowed: Literal[False] = False
    observed_fact_write_allowed: Literal[False] = False
    derived_measurement_write_allowed: Literal[False] = False
    incident_store_write_allowed: Literal[False] = False
    human_review_mutation_allowed: Literal[False] = False
    pretrip_review_mutation_allowed: Literal[False] = False
    outbound_send_allowed: Literal[False] = False
    real_sos_allowed: Literal[False] = False
    real_sms_allowed: Literal[False] = False
    real_satellite_allowed: Literal[False] = False
    hardware_control_allowed: Literal[False] = False


class AssistantSurfacePolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    surface: AssistantSurface
    constraint: AssistantSurfaceConstraint
    allowed_reads: tuple[str, ...]
    may_answer: tuple[str, ...]
    forbidden_actions: tuple[str, ...]


ASSISTANT_SURFACE_CONSTRAINTS: dict[AssistantSurface, AssistantSurfacePolicy] = {
    AssistantSurface.DEBUG: AssistantSurfacePolicy(
        surface=AssistantSurface.DEBUG,
        constraint=AssistantSurfaceConstraint.DEBUG_READ_ONLY,
        allowed_reads=(
            "debug events",
            "selected timeline node",
            "debug state",
            "debug messages",
            "Phase 3.5 boundary snapshot",
        ),
        may_answer=(
            "runtime timeline explanation",
            "L0-L4 transition explanation",
            "provider degraded status",
            "mock outbound status",
            "Ln gate and skill run visibility",
        ),
        forbidden_actions=(
            "mutate safety runtime",
            "call /safety/*",
            "send outbound",
            "change debug log",
        ),
    ),
    AssistantSurface.ADMIN: AssistantSurfacePolicy(
        surface=AssistantSurface.ADMIN,
        constraint=AssistantSurfaceConstraint.ADMIN_AFTER_ACTION_READ_ONLY,
        allowed_reads=(
            "after-action evidence tree",
            "incident package refs",
            "map/evidence selection",
            "Phase 2 preview snapshots",
        ),
        may_answer=(
            "what happened",
            "which evidence supports it",
            "which persisted package or adapter output exists",
        ),
        forbidden_actions=(
            "rewrite historical incident/evidence",
            "write Brain nodes",
            "alter after-action package",
        ),
    ),
    AssistantSurface.PRETRIP: AssistantSurfacePolicy(
        surface=AssistantSurface.PRETRIP,
        constraint=AssistantSurfaceConstraint.PRETRIP_READ_ONLY,
        allowed_reads=(
            "project manifest",
            "candidates",
            "source registry",
            "review queue",
            "readiness/departure gate artifacts",
        ),
        may_answer=(
            "planning state",
            "candidate provenance",
            "missing review items",
            "readiness blockers",
        ),
        forbidden_actions=(
            "accept/reject candidates",
            "create reviewed facts",
            "compile runtime handoff",
            "approve departure",
        ),
    ),
    AssistantSurface.HARDWARE_READINESS: AssistantSurfacePolicy(
        surface=AssistantSurface.HARDWARE_READINESS,
        constraint=AssistantSurfaceConstraint.HARDWARE_READINESS_READ_ONLY,
        allowed_reads=(
            "provider health fixture",
            "sample replay timeline",
            "runtime debug log",
            "mock transport queue",
        ),
        may_answer=(
            "provider status",
            "sample replay interpretation",
            "debug readiness checklist",
        ),
        forbidden_actions=(
            "control hardware",
            "change provider state",
            "open real transport",
            "start Pi/Docker deployment",
        ),
    ),
}


class ScoutAssistantQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")

    surface: AssistantSurface
    question: str = Field(min_length=1, max_length=2000)
    context_ref: str | None = None
    selected_event_id: str | None = None
    selected_artifact_id: str | None = None
    project_id: str | None = None


class ScoutAssistantResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    surface: AssistantSurface
    answer: str = Field(min_length=1)
    model_interpretation: Literal[True] = True
    read_only: Literal[True] = True
    sources: list[AssistantSourceRef] = Field(default_factory=list)
    boundary: AssistantBoundary
    limitations: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def boundary_must_match_surface(self) -> "ScoutAssistantResponse":
        if self.boundary.surface != self.surface:
            raise ValueError("assistant boundary surface must match response surface")
        return self
