from __future__ import annotations

import argparse
import json
import tempfile
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

from phase2_brain_models import (
    BrainNode,
    BrainNodeType,
    DecisionOptionSet,
    RemoteStatusArtifact,
    SkillDefinition,
    SkillRunRecord,
)
from phase2_brain_store import BrainFileStore
from phase2_remote_status_replay import persist_team_replay_remote_status
from phase2_team_replay_store import (
    DEFAULT_TEAM_REPLAY_FIXTURE_PATH,
    persist_team_replay_to_brain_store,
)


DEFAULT_SKILL_ROOT = Path(__file__).resolve().parent / "skills" / "scout"


@dataclass(frozen=True)
class Phase2TeamReplayDemoSummary:
    fixture_id: str
    fixture_path: str
    counts: dict[str, int]
    mission_ids: list[str]
    remote_status_ids: list[str]
    persisted_remote_status_artifact_ids: list[str]
    option_set_ids: list[str]
    option_ids: list[str]
    skill_definition_ids: list[str]
    skill_run_ids: list[str]
    skill_audit: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "fixture_id": self.fixture_id,
            "fixture_path": self.fixture_path,
            "counts": self.counts,
            "key_ids": {
                "missions": self.mission_ids,
                "remote_statuses": self.remote_status_ids,
                "persisted_remote_status_artifacts": self.persisted_remote_status_artifact_ids,
                "decision_option_sets": self.option_set_ids,
                "decision_options": self.option_ids,
                "skill_definitions": self.skill_definition_ids,
                "skill_runs": self.skill_run_ids,
            },
            "skill_audit": self.skill_audit,
        }


def run_phase2_team_replay_demo(
    *,
    store_root: Path | str | None = None,
    fixture_path: Path | str = DEFAULT_TEAM_REPLAY_FIXTURE_PATH,
    skill_root: Path | str = DEFAULT_SKILL_ROOT,
) -> Phase2TeamReplayDemoSummary:
    if store_root is None:
        with tempfile.TemporaryDirectory(prefix="scout-phase2-team-replay-") as tmpdir:
            return _run_with_store(Path(tmpdir), Path(fixture_path), Path(skill_root))
    return _run_with_store(Path(store_root), Path(fixture_path), Path(skill_root))


def _run_with_store(
    store_root: Path,
    fixture_path: Path,
    skill_root: Path,
) -> Phase2TeamReplayDemoSummary:
    store = BrainFileStore(store_root)
    replay = persist_team_replay_to_brain_store(store, fixture_path)
    remote_status_result = persist_team_replay_remote_status(store, fixture_path=fixture_path)
    fixture_payload = json.loads(fixture_path.read_text(encoding="utf-8"))

    nodes = sorted(replay.nodes, key=lambda node: node.id)
    option_sets = _nodes_of_type(nodes, DecisionOptionSet)
    remote_statuses = _nodes_of_type(nodes, RemoteStatusArtifact)
    skill_definitions = _nodes_of_type(nodes, SkillDefinition)
    skill_runs = _nodes_of_type(nodes, SkillRunRecord)

    return Phase2TeamReplayDemoSummary(
        fixture_id=str(fixture_payload["fixture_id"]),
        fixture_path=fixture_path.as_posix(),
        counts=_counts_for(nodes, store),
        mission_ids=_ids_for_type(nodes, BrainNodeType.MISSION),
        remote_status_ids=[node.id for node in remote_statuses],
        persisted_remote_status_artifact_ids=[remote_status_result.persisted.artifact.id],
        option_set_ids=[node.id for node in option_sets],
        option_ids=_option_ids(option_sets),
        skill_definition_ids=[node.id for node in skill_definitions],
        skill_run_ids=[node.id for node in skill_runs],
        skill_audit=_skill_audit(skill_definitions, skill_runs, skill_root),
    )


def _counts_for(nodes: Sequence[BrainNode], store: BrainFileStore) -> dict[str, int]:
    type_counts = Counter(node.type.value for node in nodes)
    option_count = sum(
        len(node.options) for node in nodes if isinstance(node, DecisionOptionSet)
    )
    return {
        "total_nodes": len(nodes),
        "store_nodes": len(store.list_nodes()),
        "remote_status_artifacts": type_counts[BrainNodeType.REMOTE_STATUS_ARTIFACT.value],
        "persisted_remote_status_artifacts": max(
            0,
            len(store.list_nodes(BrainNodeType.ARTIFACT))
            - type_counts[BrainNodeType.ARTIFACT.value],
        ),
        "decision_option_sets": type_counts[BrainNodeType.DECISION_OPTION_SET.value],
        "decision_options": option_count,
        "skill_definitions": type_counts[BrainNodeType.SKILL_DEFINITION.value],
        "skill_run_records": type_counts[BrainNodeType.SKILL_RUN_RECORD.value],
        "beacon_nodes": type_counts[BrainNodeType.BEACON_NODE.value],
        "team_separation_events": type_counts[BrainNodeType.TEAM_SEPARATION_EVENT.value],
    }


def _nodes_of_type(nodes: Sequence[BrainNode], model: type[Any]) -> list[Any]:
    return [node for node in nodes if isinstance(node, model)]


def _ids_for_type(nodes: Sequence[BrainNode], node_type: BrainNodeType) -> list[str]:
    return [node.id for node in nodes if node.type == node_type]


def _option_ids(option_sets: Sequence[DecisionOptionSet]) -> list[str]:
    return sorted(option.id for option_set in option_sets for option in option_set.options)


def _skill_audit(
    skill_definitions: Sequence[SkillDefinition],
    skill_runs: Sequence[SkillRunRecord],
    skill_root: Path,
) -> dict[str, Any]:
    activation_decisions = Counter(run.activation_decision for run in skill_runs)
    manifest_refs = [definition.manifest_ref for definition in skill_definitions]
    missing_manifest_refs = [
        ref for ref in sorted(manifest_refs) if not (skill_root.parent.parent / ref).exists()
    ]
    run_output_refs = sorted({ref for run in skill_runs for ref in run.output_refs})

    return {
        "skill_definitions": len(skill_definitions),
        "skill_runs": len(skill_runs),
        "activation_decisions": dict(sorted(activation_decisions.items())),
        "manifest_refs": sorted(manifest_refs),
        "manifest_refs_missing_locally": len(missing_manifest_refs),
        "missing_manifest_refs": missing_manifest_refs,
        "run_output_refs": run_output_refs,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the local Phase 2 team replay demo.")
    parser.add_argument("--store-root", type=Path, help="BrainFileStore root for demo output.")
    parser.add_argument(
        "--fixture",
        type=Path,
        default=DEFAULT_TEAM_REPLAY_FIXTURE_PATH,
        help="Team replay fixture JSON path.",
    )
    args = parser.parse_args(argv)

    summary = run_phase2_team_replay_demo(store_root=args.store_root, fixture_path=args.fixture)
    print(json.dumps(summary.to_dict(), sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
