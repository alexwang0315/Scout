from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from phase2_brain_models import Artifact, ArtifactKind, RemoteStatusArtifact
from phase2_brain_store import BrainFileStore
from phase2_store_utils import append_unique, id_token


_REMOTE_STATUS_PREFIX = "remote_status."


@dataclass(frozen=True)
class PersistedRemoteStatusArtifact:
    remote_status: RemoteStatusArtifact
    artifact: Artifact
    remote_status_path: Path
    artifact_node_path: Path
    artifact_file_path: Path


def persist_remote_status_artifact(
    store: BrainFileStore,
    remote_status: RemoteStatusArtifact,
) -> PersistedRemoteStatusArtifact:
    artifact_id = _artifact_id_for(remote_status)
    artifact_uri = _artifact_uri_for(remote_status)
    artifact_file_path = store.root / artifact_uri
    payload = _artifact_payload(remote_status)
    content = json.dumps(payload, separators=(",", ":"), sort_keys=True) + "\n"
    digest = hashlib.sha256(content.encode("utf-8")).hexdigest()

    artifact = Artifact(
        id=artifact_id,
        mission_id=remote_status.mission_id,
        created_at=remote_status.generated_at,
        artifact_kind=ArtifactKind.REMOTE_STATUS_JSON,
        uri=artifact_uri,
        media_type="application/json",
        sha256=digest,
        captured_at=remote_status.generated_at,
        metadata={
            "artifact_origin": "generated",
            "remote_status_ref": remote_status.id,
        },
    )
    linked_remote_status = remote_status.model_copy(
        update={"artifact_refs": append_unique(remote_status.artifact_refs, artifact.id)}
    )

    artifact_file_path.parent.mkdir(parents=True, exist_ok=True)
    artifact_file_path.write_text(content, encoding="utf-8")
    artifact_node_path = store.write_node(artifact)
    remote_status_path = store.write_node(linked_remote_status, strict_artifact_refs=True)

    return PersistedRemoteStatusArtifact(
        remote_status=linked_remote_status,
        artifact=artifact,
        remote_status_path=remote_status_path,
        artifact_node_path=artifact_node_path,
        artifact_file_path=artifact_file_path,
    )


def _artifact_payload(remote_status: RemoteStatusArtifact) -> dict[str, object]:
    return {
        "id": remote_status.id,
        "mission_id": remote_status.mission_id,
        "generated_at": remote_status.generated_at,
        "freshness_seconds": remote_status.freshness_seconds,
        "status": remote_status.status,
        "team_summary": remote_status.team_summary,
        "latest_checkpoint": remote_status.latest_checkpoint,
        "next_checkpoint": remote_status.next_checkpoint,
        "safety_level": remote_status.safety_level,
        "uncertainty": remote_status.uncertainty.value,
        "message": remote_status.message,
    }


def _artifact_id_for(remote_status: RemoteStatusArtifact) -> str:
    token = remote_status.id
    if token.startswith(_REMOTE_STATUS_PREFIX):
        token = token.removeprefix(_REMOTE_STATUS_PREFIX)
    return "artifact.remote_status_json." + id_token(token)


def _artifact_uri_for(remote_status: RemoteStatusArtifact) -> str:
    token = remote_status.id
    if token.startswith(_REMOTE_STATUS_PREFIX):
        token = token.removeprefix(_REMOTE_STATUS_PREFIX)
    return f"artifacts/remote-status/{id_token(token)}.json"
