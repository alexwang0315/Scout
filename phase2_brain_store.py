from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from phase2_brain_models import (
    Artifact,
    BeaconNode,
    BrainNode,
    BrainNodeType,
    Checkpoint,
    DecisionOptionSet,
    DerivedMeasurement,
    Device,
    Equipment,
    HumanReview,
    Mission,
    ModelInterpretation,
    ObservedFact,
    Person,
    RemoteStatusArtifact,
    Route,
    Segment,
    SignalBearingMeasurement,
    SkillDefinition,
    SkillRunRecord,
    Team,
    TeamSeparationEvent,
)
from phase2_refs import explicit_artifact_refs_for


NODE_MODELS: dict[BrainNodeType, type[BrainNode]] = {
    BrainNodeType.MISSION: Mission,
    BrainNodeType.TEAM: Team,
    BrainNodeType.PERSON: Person,
    BrainNodeType.DEVICE: Device,
    BrainNodeType.EQUIPMENT: Equipment,
    BrainNodeType.ROUTE: Route,
    BrainNodeType.SEGMENT: Segment,
    BrainNodeType.CHECKPOINT: Checkpoint,
    BrainNodeType.OBSERVED_FACT: ObservedFact,
    BrainNodeType.DERIVED_MEASUREMENT: DerivedMeasurement,
    BrainNodeType.MODEL_INTERPRETATION: ModelInterpretation,
    BrainNodeType.HUMAN_REVIEW: HumanReview,
    BrainNodeType.SKILL_DEFINITION: SkillDefinition,
    BrainNodeType.SKILL_RUN_RECORD: SkillRunRecord,
    BrainNodeType.ARTIFACT: Artifact,
    BrainNodeType.REMOTE_STATUS_ARTIFACT: RemoteStatusArtifact,
    BrainNodeType.DECISION_OPTION_SET: DecisionOptionSet,
    BrainNodeType.BEACON_NODE: BeaconNode,
    BrainNodeType.TEAM_SEPARATION_EVENT: TeamSeparationEvent,
    BrainNodeType.SIGNAL_BEARING_MEASUREMENT: SignalBearingMeasurement,
}


NODE_DIRECTORIES: dict[BrainNodeType, str] = {
    BrainNodeType.MISSION: "missions",
    BrainNodeType.TEAM: "teams",
    BrainNodeType.PERSON: "people",
    BrainNodeType.DEVICE: "devices",
    BrainNodeType.EQUIPMENT: "equipment",
    BrainNodeType.ROUTE: "routes",
    BrainNodeType.SEGMENT: "segments",
    BrainNodeType.CHECKPOINT: "checkpoints",
    BrainNodeType.OBSERVED_FACT: "facts",
    BrainNodeType.DERIVED_MEASUREMENT: "measurements",
    BrainNodeType.MODEL_INTERPRETATION: "interpretations",
    BrainNodeType.HUMAN_REVIEW: "reviews",
    BrainNodeType.SKILL_DEFINITION: "skill-definitions",
    BrainNodeType.SKILL_RUN_RECORD: "skill-runs",
    BrainNodeType.ARTIFACT: "artifacts",
    BrainNodeType.REMOTE_STATUS_ARTIFACT: "remote-status-artifacts",
    BrainNodeType.DECISION_OPTION_SET: "decision-option-sets",
    BrainNodeType.BEACON_NODE: "beacon-nodes",
    BrainNodeType.TEAM_SEPARATION_EVENT: "team-separation-events",
    BrainNodeType.SIGNAL_BEARING_MEASUREMENT: "signal-bearing-measurements",
}


class MissingArtifactReferenceError(ValueError):
    pass


class BrainFileStore:
    def __init__(self, root: Path | str):
        self.root = Path(root)
        self.index_dir = self.root / "indexes"
        self.index_path = self.index_dir / "nodes.json"

    def write_node(self, node: BrainNode, *, strict_artifact_refs: bool = False) -> Path:
        if strict_artifact_refs:
            self.validate_artifact_refs(node)

        path = self.path_for_node(node)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(node.model_dump(mode="json"), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        self._write_index({**self._read_index(), node.id: self._index_entry(node, path)})
        return path

    def load_node(self, node_id: str) -> BrainNode:
        index = self._read_index()
        if node_id in index:
            path = self.root / index[node_id]["path"]
            if path.exists():
                return self._load_path(path)

        for path in self._node_paths():
            payload = json.loads(path.read_text(encoding="utf-8"))
            if payload.get("id") == node_id:
                return self._validate_payload(payload)

        raise KeyError(node_id)

    def list_nodes(self, node_type: BrainNodeType | None = None) -> list[BrainNode]:
        nodes = [self._load_path(path) for path in self._node_paths()]
        if node_type is None:
            return sorted(nodes, key=lambda node: node.id)
        return sorted((node for node in nodes if node.type == node_type), key=lambda node: node.id)

    def rebuild_index(self) -> dict[str, dict[str, str]]:
        index: dict[str, dict[str, str]] = {}
        for path in self._node_paths():
            node = self._load_path(path)
            index[node.id] = self._index_entry(node, path)
        self._write_index(index)
        return index

    def validate_artifact_refs(self, node: BrainNode) -> None:
        missing = [ref for ref in explicit_artifact_refs_for(node) if not self._artifact_exists(ref)]
        if missing:
            raise MissingArtifactReferenceError(
                f"{node.id} references missing artifacts: {', '.join(sorted(missing))}"
            )

    def path_for_node(self, node: BrainNode) -> Path:
        return self.root / NODE_DIRECTORIES[node.type] / f"{_filename_for_id(node.id)}.json"

    def _artifact_exists(self, artifact_id: str) -> bool:
        try:
            node = self.load_node(artifact_id)
        except KeyError:
            return False
        return node.type == BrainNodeType.ARTIFACT

    def _load_path(self, path: Path) -> BrainNode:
        return self._validate_payload(json.loads(path.read_text(encoding="utf-8")))

    def _validate_payload(self, payload: dict[str, Any]) -> BrainNode:
        node_type = BrainNodeType(payload["type"])
        return NODE_MODELS[node_type].model_validate(payload)

    def _node_paths(self) -> list[Path]:
        paths: list[Path] = []
        for directory in NODE_DIRECTORIES.values():
            paths.extend((self.root / directory).glob("*.json"))
        return sorted(paths)

    def _read_index(self) -> dict[str, dict[str, str]]:
        if not self.index_path.exists():
            return {}
        return json.loads(self.index_path.read_text(encoding="utf-8"))

    def _write_index(self, index: dict[str, dict[str, str]]) -> None:
        self.index_dir.mkdir(parents=True, exist_ok=True)
        self.index_path.write_text(
            json.dumps(index, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    def _index_entry(self, node: BrainNode, path: Path) -> dict[str, str]:
        return {
            "type": node.type.value,
            "path": path.relative_to(self.root).as_posix(),
        }


def _filename_for_id(node_id: str) -> str:
    return node_id.replace("/", "_")
