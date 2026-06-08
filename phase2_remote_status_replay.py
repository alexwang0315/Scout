from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from phase2_brain_models import Artifact, BrainNodeType, RemoteStatusArtifact
from phase2_brain_store import BrainFileStore
from phase2_demo_defaults import DEFAULT_TEAM_REPLAY_FIXTURE_PATH
from remote_status_store import PersistedRemoteStatusArtifact, persist_remote_status_artifact


TEAM_REPLAY_FIXTURE_PATH = DEFAULT_TEAM_REPLAY_FIXTURE_PATH


@dataclass(frozen=True)
class TeamReplayRemoteStatusPersistence:
    fixture_path: Path
    remote_status: RemoteStatusArtifact
    seeded_artifacts: tuple[Artifact, ...]
    persisted: PersistedRemoteStatusArtifact


def persist_team_replay_remote_status(
    store: BrainFileStore,
    *,
    fixture_path: Path | str = TEAM_REPLAY_FIXTURE_PATH,
    remote_status_id: str | None = None,
) -> TeamReplayRemoteStatusPersistence:
    fixture_path = Path(fixture_path)
    fixture = _load_fixture(fixture_path)
    remote_status = _remote_status_from_fixture(fixture, remote_status_id=remote_status_id)
    seeded_artifacts = _seed_fixture_artifact_refs(store, fixture, remote_status.artifact_refs)
    persisted = persist_remote_status_artifact(store, remote_status)

    return TeamReplayRemoteStatusPersistence(
        fixture_path=fixture_path,
        remote_status=remote_status,
        seeded_artifacts=tuple(seeded_artifacts),
        persisted=persisted,
    )


def _load_fixture(fixture_path: Path) -> dict[str, Any]:
    return json.loads(fixture_path.read_text(encoding="utf-8"))


def _remote_status_from_fixture(
    fixture: dict[str, Any],
    *,
    remote_status_id: str | None,
) -> RemoteStatusArtifact:
    payloads = [
        payload
        for payload in fixture["nodes"]
        if payload.get("type") == BrainNodeType.REMOTE_STATUS_ARTIFACT.value
    ]
    if remote_status_id is not None:
        payloads = [payload for payload in payloads if payload.get("id") == remote_status_id]
    if len(payloads) != 1:
        target = remote_status_id or "single RemoteStatusArtifact"
        raise ValueError(f"Expected {target} in team replay fixture, found {len(payloads)}")
    return RemoteStatusArtifact.model_validate(payloads[0])


def _seed_fixture_artifact_refs(
    store: BrainFileStore,
    fixture: dict[str, Any],
    artifact_refs: list[str],
) -> list[Artifact]:
    artifact_payloads = {
        payload["id"]: payload
        for payload in fixture["nodes"]
        if payload.get("type") == BrainNodeType.ARTIFACT.value
    }

    artifacts: list[Artifact] = []
    for artifact_ref in artifact_refs:
        if artifact_ref not in artifact_payloads:
            raise ValueError(f"RemoteStatusArtifact references missing fixture Artifact: {artifact_ref}")
        artifact = Artifact.model_validate(artifact_payloads[artifact_ref])
        store.write_node(artifact)
        artifacts.append(artifact)
    return artifacts
