from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from scout_hardware_prototype_prep import (
    ScoutHardwarePrototypeTargetProfile,
    build_scout_hardware_prototype_preflight,
)


class PiFixtureSmokeBoundary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    manual_only: bool = True
    operator_must_execute: bool = True
    network_calls_performed: bool = False
    safety_mutation_performed: bool = False
    phase1_safety_decision_mutation_allowed: bool = False
    outbound_messages_allowed: bool = False
    local_model_start_allowed: bool = False
    hardware_provider_control_allowed: bool = False


class PiFixtureSmokeCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    command_id: str
    method: Literal["GET", "POST"]
    url: str
    mutation: bool
    operator_only: bool
    example_command: str


class PiFixtureSmokeCounts(BaseModel):
    model_config = ConfigDict(extra="forbid")

    command_count: int
    safety_mutation_command_count: int
    blocker_count: int


class PiFixtureSmokePlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_kind: Literal["pi_fixture_smoke_plan"]
    target_id: str
    status: Literal["manual_smoke_ready", "blocked"]
    blockers: list[str]
    commands: list[PiFixtureSmokeCommand]
    boundary: PiFixtureSmokeBoundary
    counts: PiFixtureSmokeCounts


def load_manual_observation_fixture(path: Path | str) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def build_pi_fixture_smoke_plan(
    profile: ScoutHardwarePrototypeTargetProfile,
    observation_fixture_path: Path | str,
) -> PiFixtureSmokePlan:
    preflight = build_scout_hardware_prototype_preflight(profile)
    if preflight.blockers:
        return _plan(profile, preflight.blockers, [])

    runtime_base = profile.runtime_base_url.rstrip("/")
    fixture_path = str(observation_fixture_path)
    commands = [
        PiFixtureSmokeCommand(
            command_id="runtime_health",
            method="GET",
            url=f"{runtime_base}/health",
            mutation=False,
            operator_only=True,
            example_command=f"curl --max-time 5 {runtime_base}/health",
        ),
        PiFixtureSmokeCommand(
            command_id="runtime_status",
            method="GET",
            url=f"{runtime_base}/runtime/status",
            mutation=False,
            operator_only=True,
            example_command=f"curl --max-time 5 {runtime_base}/runtime/status",
        ),
        PiFixtureSmokeCommand(
            command_id="provider_status",
            method="GET",
            url=f"{runtime_base}/providers/status",
            mutation=False,
            operator_only=True,
            example_command=f"curl --max-time 5 {runtime_base}/providers/status",
        ),
        PiFixtureSmokeCommand(
            command_id="fixture_observation_ingest",
            method="POST",
            url=f"{runtime_base}/safety/observations",
            mutation=True,
            operator_only=True,
            example_command=(
                f"curl --max-time 5 -X POST {runtime_base}/safety/observations "
                "-H 'Content-Type: application/json' "
                f"--data @{fixture_path}"
            ),
        ),
    ]
    return _plan(profile, [], commands)


def _plan(
    profile: ScoutHardwarePrototypeTargetProfile,
    blockers: list[str],
    commands: list[PiFixtureSmokeCommand],
) -> PiFixtureSmokePlan:
    return PiFixtureSmokePlan(
        artifact_kind="pi_fixture_smoke_plan",
        target_id=profile.target_id,
        status="blocked" if blockers else "manual_smoke_ready",
        blockers=blockers,
        commands=commands,
        boundary=PiFixtureSmokeBoundary(),
        counts=PiFixtureSmokeCounts(
            command_count=len(commands),
            safety_mutation_command_count=sum(1 for command in commands if command.mutation),
            blocker_count=len(blockers),
        ),
    )
