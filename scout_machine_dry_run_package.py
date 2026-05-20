from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from scout_hardware_prototype_prep import (
    ScoutHardwarePrototypeTargetProfile,
    build_scout_hardware_prototype_preflight,
)
from scout_pi_fixture_smoke import build_pi_fixture_smoke_plan


class ScoutMachineDryRunBoundary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    manual_only: bool = True
    operator_must_execute: bool = True
    network_calls_performed: bool = False
    docker_commands_executed: bool = False
    safety_mutation_performed: bool = False
    local_model_start_allowed: bool = False
    outbound_messages_allowed: bool = False
    hardware_provider_control_allowed: bool = False
    phase1_safety_decision_mutation_allowed: bool = False


class ScoutMachineDryRunWorksheet(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_id: str
    host_label: str
    runtime_base_url: str
    data_root: str
    runtime_profile: str
    operator_started_services: bool


class ScoutMachineDryRunEvidenceTemplate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    evidence_id: str
    required_fields: list[str] = Field(min_length=1)
    redacted_fields: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class ScoutMachineDryRunCounts(BaseModel):
    model_config = ConfigDict(extra="forbid")

    manual_command_count: int
    safety_mutation_command_count: int
    stop_condition_count: int
    blocker_count: int


class ScoutMachineDryRunPackage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_kind: Literal["scout_machine_manual_dry_run_package"]
    target_id: str
    status: Literal["ready_for_operator_dry_run", "blocked"]
    blockers: list[str]
    worksheet: ScoutMachineDryRunWorksheet
    manual_commands: list[str]
    evidence_template: ScoutMachineDryRunEvidenceTemplate
    stop_conditions: list[str]
    boundary: ScoutMachineDryRunBoundary
    counts: ScoutMachineDryRunCounts


def build_scout_machine_dry_run_package(
    profile: ScoutHardwarePrototypeTargetProfile,
    *,
    observation_fixture_path: Path | str,
) -> ScoutMachineDryRunPackage:
    preflight = build_scout_hardware_prototype_preflight(profile)
    fixture_plan = build_pi_fixture_smoke_plan(profile, observation_fixture_path)
    blockers = sorted(set(preflight.blockers + fixture_plan.blockers))
    manual_commands = [command.example_command for command in fixture_plan.commands]

    return ScoutMachineDryRunPackage(
        artifact_kind="scout_machine_manual_dry_run_package",
        target_id=profile.target_id,
        status="blocked" if blockers else "ready_for_operator_dry_run",
        blockers=blockers,
        worksheet=ScoutMachineDryRunWorksheet(
            target_id=profile.target_id,
            host_label=profile.host_label,
            runtime_base_url=profile.runtime_base_url,
            data_root=profile.data_root,
            runtime_profile=profile.runtime_profile,
            operator_started_services=profile.operator_started_services,
        ),
        manual_commands=manual_commands,
        evidence_template=_evidence_template(profile),
        stop_conditions=_stop_conditions(),
        boundary=ScoutMachineDryRunBoundary(),
        counts=ScoutMachineDryRunCounts(
            manual_command_count=len(manual_commands),
            safety_mutation_command_count=sum(
                1 for command in manual_commands if "/safety/observations" in command
            ),
            stop_condition_count=len(_stop_conditions()),
            blocker_count=len(blockers),
        ),
    )


def _evidence_template(
    profile: ScoutHardwarePrototypeTargetProfile,
) -> ScoutMachineDryRunEvidenceTemplate:
    return ScoutMachineDryRunEvidenceTemplate(
        evidence_id=f"{profile.target_id}.manual_dry_run.evidence",
        required_fields=[
            "operator_alias",
            "target_id",
            "host_label",
            "started_at",
            "health_status",
            "runtime_status",
            "provider_status",
            "incident_store_path",
            "stop_conditions_checked",
        ],
        redacted_fields=["token", "secret", "api_key", "authorization"],
        notes=[
            "Record command outputs manually; this package does not execute them.",
            "Do not include credential values in evidence artifacts.",
        ],
    )


def _stop_conditions() -> list[str]:
    return [
        "health_status_degraded_without_known_optional_provider_reason",
        "data_root_not_data_scout",
        "runtime_profile_not_pi_field",
        "live_hardware_enabled",
        "ai_or_local_model_enabled",
        "event_bus_enabled",
        "outbound_or_sos_path_attempted",
        "hardware_provider_control_attempted",
    ]
