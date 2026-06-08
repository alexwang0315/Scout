from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any, Literal

from fastapi.testclient import TestClient
from pydantic import BaseModel, ConfigDict

from scout_pi_runtime import create_pi_runtime_app
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


class PiCanonicalFixtureLocalDryRunBoundary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    local_runtime_only: bool = True
    target_network_calls_performed: bool = False
    target_safety_mutation_performed: bool = False
    local_safety_mutation_performed: bool = True
    outbound_messages_allowed: bool = False
    local_model_start_allowed: bool = False
    hardware_provider_control_allowed: bool = False


class PiCanonicalFixtureLocalDryRunCounts(BaseModel):
    model_config = ConfigDict(extra="forbid")

    observations_delta: int
    checkpoint_hits_delta: int
    incident_file_count: int
    blocker_count: int


class PiCanonicalFixtureLocalDryRunResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_kind: Literal["pi_canonical_fixture_local_dry_run"]
    fixture_path: str
    status: Literal["passed", "failed"]
    blockers: list[str]
    safety_level: str | None
    available_capabilities: list[str]
    checkpoint_ids: list[str]
    recording_profiles: list[str]
    boundary: PiCanonicalFixtureLocalDryRunBoundary
    counts: PiCanonicalFixtureLocalDryRunCounts


def load_manual_observation_fixture(path: Path | str) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def build_canonical_fixture_local_dry_run(
    observation_fixture_path: Path | str,
    *,
    mission_graph_path: Path | str,
) -> PiCanonicalFixtureLocalDryRunResult:
    fixture_path = Path(observation_fixture_path)
    fixture = load_manual_observation_fixture(fixture_path)

    with tempfile.TemporaryDirectory() as tmpdir:
        app = create_pi_runtime_app(
            {
                "SCOUT_DATA_ROOT": tmpdir,
                "SCOUT_SAFETY_MISSION_GRAPH": str(mission_graph_path),
                "SCOUT_SAFETY_INCIDENT_STORE": str(Path(tmpdir) / "incidents"),
                "SCOUT_ENABLE_LIVE_HARDWARE": "0",
                "SCOUT_ENABLE_AI_INFERENCE": "0",
                "SCOUT_ENABLE_LOCAL_MODEL": "0",
                "SCOUT_EVENT_BUS": "none",
            }
        )
        client = TestClient(app)

        before = client.get("/runtime/status").json()
        response = client.post("/safety/observations", json=fixture)
        after = client.get("/runtime/status").json()

    response_body = (
        response.json()
        if response.headers.get("content-type", "").startswith("application/json")
        else {}
    )
    capabilities = response_body.get("latest_capabilities") or {}
    available_capabilities = sorted(
        name
        for name, capability in capabilities.items()
        if isinstance(capability, dict) and capability.get("status") == "available"
    )
    checkpoint_ids = [
        arrival.get("checkpoint", {}).get("checkpoint_id")
        for arrival in response_body.get("checkpoint_arrivals", [])
        if isinstance(arrival, dict)
    ]
    checkpoint_ids = [checkpoint_id for checkpoint_id in checkpoint_ids if checkpoint_id]
    recording_profiles = [
        profile
        for profile in response_body.get("recording_profiles", [])
        if isinstance(profile, str)
    ]

    blockers = _canonical_fixture_dry_run_blockers(
        status_code=response.status_code,
        response_body=response_body,
        before=before,
        after=after,
        available_capabilities=available_capabilities,
        checkpoint_ids=checkpoint_ids,
    )
    return PiCanonicalFixtureLocalDryRunResult(
        artifact_kind="pi_canonical_fixture_local_dry_run",
        fixture_path=str(fixture_path),
        status="failed" if blockers else "passed",
        blockers=blockers,
        safety_level=response_body.get("safety_level"),
        available_capabilities=available_capabilities,
        checkpoint_ids=checkpoint_ids,
        recording_profiles=recording_profiles,
        boundary=PiCanonicalFixtureLocalDryRunBoundary(),
        counts=PiCanonicalFixtureLocalDryRunCounts(
            observations_delta=(
                after.get("observations_processed", 0)
                - before.get("observations_processed", 0)
            ),
            checkpoint_hits_delta=(
                after.get("checkpoint_hits", 0) - before.get("checkpoint_hits", 0)
            ),
            incident_file_count=len(response_body.get("stored_incident_paths") or []),
            blocker_count=len(blockers),
        ),
    )


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


def _canonical_fixture_dry_run_blockers(
    *,
    status_code: int,
    response_body: dict[str, Any],
    before: dict[str, Any],
    after: dict[str, Any],
    available_capabilities: list[str],
    checkpoint_ids: list[str],
) -> list[str]:
    blockers: list[str] = []
    if status_code != 200:
        blockers.append(f"unexpected_status_code:{status_code}")
    if response_body.get("status") != "accepted":
        blockers.append("observation_not_accepted")
    if after.get("observations_processed", 0) - before.get("observations_processed", 0) != 1:
        blockers.append("observations_delta_not_one")
    if response_body.get("safety_level") != "L0_NORMAL" or after.get("safety_level") != "L0_NORMAL":
        blockers.append("safety_level_not_l0_normal")
    required_capabilities = {
        "gps",
        "gps_horizontal_accuracy",
        "imu",
        "battery",
        "pedometer_distance",
        "pedometer_steps",
    }
    missing = sorted(required_capabilities - set(available_capabilities))
    blockers.extend(f"capability_unavailable:{name}" for name in missing)
    if "cp_01" not in checkpoint_ids:
        blockers.append("route_checkpoint_cp_01_not_hit")
    if response_body.get("incident_ids"):
        blockers.append("unexpected_incident_ids")
    if response_body.get("stored_incident_paths"):
        blockers.append("unexpected_stored_incident_paths")
    return blockers


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
