from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from phase2_artifact_manifest import Phase2ArtifactManifest, build_phase2_artifact_manifest
from phase2_brain_models import Artifact, ArtifactKind
from phase2_brain_store import BrainFileStore


MANIFEST_ARTIFACT_ID = "artifact.phase2_artifact_manifest"
MANIFEST_ARTIFACT_URI = "artifacts/manifests/phase2-artifact-manifest.json"
MANIFEST_METADATA_ROLE = "phase2_artifact_manifest"


@dataclass(frozen=True)
class PersistedPhase2ArtifactManifest:
    manifest: Phase2ArtifactManifest
    artifact: Artifact
    artifact_node_path: Path
    artifact_file_path: Path


def persist_phase2_artifact_manifest(
    store: BrainFileStore,
    *,
    artifact_id: str = MANIFEST_ARTIFACT_ID,
    artifact_uri: str = MANIFEST_ARTIFACT_URI,
) -> PersistedPhase2ArtifactManifest:
    manifest = _build_rebuildable_manifest(store)
    content = _manifest_content(manifest)
    digest = hashlib.sha256(content.encode("utf-8")).hexdigest()

    artifact = Artifact(
        id=artifact_id,
        artifact_kind=ArtifactKind.OTHER,
        uri=artifact_uri,
        media_type="application/json",
        sha256=digest,
        metadata={
            "role": MANIFEST_METADATA_ROLE,
            "rebuildable": True,
            "source_of_truth": False,
        },
    )

    artifact_file_path = store.root / artifact_uri
    artifact_file_path.parent.mkdir(parents=True, exist_ok=True)
    artifact_file_path.write_text(content, encoding="utf-8")
    artifact_node_path = store.write_node(artifact)

    return PersistedPhase2ArtifactManifest(
        manifest=manifest,
        artifact=artifact,
        artifact_node_path=artifact_node_path,
        artifact_file_path=artifact_file_path,
    )


def _build_rebuildable_manifest(store: BrainFileStore) -> Phase2ArtifactManifest:
    manifest = build_phase2_artifact_manifest(store)
    manifest_artifact_ids = _manifest_artifact_ids(store)
    if not manifest_artifact_ids:
        return manifest

    manifest_dict = manifest.to_dict()
    artifacts = [
        artifact
        for artifact in manifest_dict["artifacts"]
        if artifact["id"] not in manifest_artifact_ids
    ]
    remote_status_json_artifacts = [
        artifact
        for artifact in manifest_dict["remote_status_json_artifacts"]
        if artifact["id"] not in manifest_artifact_ids
    ]
    counts = _counts_without_manifest_artifacts(manifest_dict["counts"], len(manifest_artifact_ids))

    return Phase2ArtifactManifest(
        store_root=manifest.store_root,
        counts=counts,
        artifacts=artifacts,
        remote_status_json_artifacts=remote_status_json_artifacts,
        decision_option_set_refs=manifest.decision_option_set_refs,
        skill_run_refs=manifest.skill_run_refs,
        case_replay_refs=manifest.case_replay_refs,
        phase1_adapter_evidence=manifest.phase1_adapter_evidence,
    )


def _manifest_content(manifest: Phase2ArtifactManifest) -> str:
    return json.dumps(manifest.to_dict(), separators=(",", ":"), sort_keys=True) + "\n"


def _manifest_artifact_ids(store: BrainFileStore) -> set[str]:
    return {
        node.id
        for node in store.list_nodes()
        if isinstance(node, Artifact)
        and node.metadata.get("role") == MANIFEST_METADATA_ROLE
        and node.metadata.get("source_of_truth") is False
    }


def _counts_without_manifest_artifacts(
    counts: dict[str, Any],
    manifest_artifact_count: int,
) -> dict[str, int]:
    adjusted = dict(counts)
    for key in ("total_nodes", "artifact_nodes", "Artifact"):
        if key in adjusted:
            adjusted[key] -= manifest_artifact_count
    return adjusted
