from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from phase2_brain_models import Artifact, BrainNode
from phase2_brain_store import BrainFileStore, MissingArtifactReferenceError, NODE_MODELS
from phase2_demo_defaults import DEFAULT_TEAM_REPLAY_FIXTURE_PATH
from phase2_refs import explicit_artifact_refs_for


@dataclass(frozen=True)
class TeamReplayStoreResult:
    fixture_path: Path
    nodes: list[BrainNode]
    paths: list[Path]

    @property
    def node_ids(self) -> list[str]:
        return [node.id for node in self.nodes]


def load_team_replay_nodes(
    fixture_path: Path | str = DEFAULT_TEAM_REPLAY_FIXTURE_PATH,
) -> list[BrainNode]:
    payload = json.loads(Path(fixture_path).read_text(encoding="utf-8"))
    nodes = [_validate_node(node_payload) for node_payload in payload["nodes"]]
    _require_unique_node_ids(nodes)
    _validate_explicit_artifact_refs(nodes)
    return nodes


def persist_team_replay_to_brain_store(
    store: BrainFileStore,
    fixture_path: Path | str = DEFAULT_TEAM_REPLAY_FIXTURE_PATH,
    *,
    strict_artifact_refs: bool = True,
) -> TeamReplayStoreResult:
    fixture = Path(fixture_path)
    nodes = load_team_replay_nodes(fixture)
    paths: list[Path] = []

    for node in _artifacts_first(nodes):
        paths.append(store.write_node(node, strict_artifact_refs=strict_artifact_refs))

    return TeamReplayStoreResult(fixture_path=fixture, nodes=nodes, paths=paths)


def _validate_node(payload: dict[str, Any]) -> BrainNode:
    node_type = payload["type"]
    model = NODE_MODELS[node_type]
    return model.model_validate(payload)


def _require_unique_node_ids(nodes: list[BrainNode]) -> None:
    seen: set[str] = set()
    duplicates: list[str] = []
    for node in nodes:
        if node.id in seen:
            duplicates.append(node.id)
        seen.add(node.id)

    if duplicates:
        raise ValueError(f"duplicate team replay node ids: {', '.join(sorted(duplicates))}")


def _validate_explicit_artifact_refs(nodes: list[BrainNode]) -> None:
    artifact_ids = {node.id for node in nodes if isinstance(node, Artifact)}
    missing: dict[str, list[str]] = {}

    for node in nodes:
        refs = explicit_artifact_refs_for(node)
        unresolved = [ref for ref in refs if ref not in artifact_ids]
        if unresolved:
            missing[node.id] = sorted(unresolved)

    if missing:
        details = "; ".join(
            f"{node_id}: {', '.join(refs)}" for node_id, refs in sorted(missing.items())
        )
        raise MissingArtifactReferenceError(f"missing team replay artifact refs: {details}")


def _artifacts_first(nodes: list[BrainNode]) -> list[BrainNode]:
    artifacts = [node for node in nodes if isinstance(node, Artifact)]
    others = [node for node in nodes if not isinstance(node, Artifact)]
    return artifacts + others
