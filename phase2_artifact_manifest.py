from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from phase2_brain_models import (
    Artifact,
    ArtifactKind,
    BrainNode,
    DecisionOptionSet,
    DerivedMeasurement,
    ObservedFact,
    RemoteStatusArtifact,
    SkillRunRecord,
    TeamSeparationEvent,
)
from phase2_brain_store import BrainFileStore


REMOTE_STATUS_JSON_ARTIFACT_ID_PREFIX = "artifact.remote_status_json."
GENERATED_REMOTE_STATUS_JSON_URI_PREFIX = "artifacts/remote-status/"


@dataclass(frozen=True)
class Phase2ArtifactManifest:
    store_root: str
    counts: dict[str, int]
    artifacts: list[dict[str, Any]]
    remote_status_json_artifacts: list[dict[str, Any]]
    decision_option_set_refs: list[dict[str, Any]]
    skill_run_refs: list[dict[str, Any]]
    case_replay_refs: list[dict[str, Any]]
    phase1_adapter_evidence: list[dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        return {
            "store_root": self.store_root,
            "counts": self.counts,
            "artifacts": self.artifacts,
            "remote_status_json_artifacts": self.remote_status_json_artifacts,
            "decision_option_set_refs": self.decision_option_set_refs,
            "skill_run_refs": self.skill_run_refs,
            "case_replay_refs": self.case_replay_refs,
            "phase1_adapter_evidence": self.phase1_adapter_evidence,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, sort_keys=True) + "\n"


def build_phase2_artifact_manifest(
    source: BrainFileStore | Path | str,
) -> Phase2ArtifactManifest:
    store = source if isinstance(source, BrainFileStore) else BrainFileStore(source)
    nodes = store.list_nodes()
    artifacts = sorted(_nodes_of_type(nodes, Artifact), key=lambda node: node.id)
    remote_statuses = sorted(_nodes_of_type(nodes, RemoteStatusArtifact), key=lambda node: node.id)
    option_sets = sorted(_nodes_of_type(nodes, DecisionOptionSet), key=lambda node: node.id)
    skill_runs = sorted(_nodes_of_type(nodes, SkillRunRecord), key=lambda node: node.id)
    separation_events = sorted(_nodes_of_type(nodes, TeamSeparationEvent), key=lambda node: node.id)
    facts = sorted(_nodes_of_type(nodes, ObservedFact), key=lambda node: node.id)
    measurements = sorted(_nodes_of_type(nodes, DerivedMeasurement), key=lambda node: node.id)

    artifact_entries = [_artifact_entry(artifact) for artifact in artifacts]
    artifact_entries_by_id = {entry["id"]: entry for entry in artifact_entries}

    return Phase2ArtifactManifest(
        store_root=store.root.as_posix(),
        counts=_counts(nodes, artifacts),
        artifacts=artifact_entries,
        remote_status_json_artifacts=_remote_status_json_entries(
            artifacts,
            remote_statuses,
            artifact_entries_by_id,
        ),
        decision_option_set_refs=[_option_set_entry(option_set) for option_set in option_sets],
        skill_run_refs=[_skill_run_entry(skill_run) for skill_run in skill_runs],
        case_replay_refs=_case_replay_entries(
            remote_statuses=remote_statuses,
            option_sets=option_sets,
            skill_runs=skill_runs,
            separation_events=separation_events,
        ),
        phase1_adapter_evidence=_phase1_adapter_evidence_entries(
            artifacts=artifacts,
            facts=facts,
            measurements=measurements,
        ),
    )


def _counts(nodes: list[BrainNode], artifacts: list[Artifact]) -> dict[str, int]:
    by_type = Counter(node.type.value for node in nodes)
    counts: dict[str, int] = {
        "total_nodes": len(nodes),
        "artifact_nodes": len(artifacts),
        "remote_status_json_artifacts": sum(
            artifact.artifact_kind == ArtifactKind.REMOTE_STATUS_JSON for artifact in artifacts
        ),
    }
    counts.update({key: by_type[key] for key in sorted(by_type)})
    return counts


def _artifact_entry(artifact: Artifact) -> dict[str, Any]:
    _validate_remote_status_json_artifact(artifact)
    entry: dict[str, Any] = {
        "id": artifact.id,
        "artifact_kind": artifact.artifact_kind.value,
        "uri": artifact.uri,
    }
    if artifact.sha256:
        entry["sha256"] = artifact.sha256
    if artifact.media_type:
        entry["media_type"] = artifact.media_type
    if artifact.mission_id:
        entry["mission_id"] = artifact.mission_id
    remote_status_ref = artifact.metadata.get("remote_status_ref")
    if remote_status_ref:
        entry["remote_status_ref"] = remote_status_ref
    artifact_origin = artifact.metadata.get("artifact_origin")
    if artifact_origin:
        entry["artifact_origin"] = artifact_origin
    return entry


def _validate_remote_status_json_artifact(artifact: Artifact) -> None:
    if artifact.artifact_kind != ArtifactKind.REMOTE_STATUS_JSON:
        return

    if not artifact.id.startswith(REMOTE_STATUS_JSON_ARTIFACT_ID_PREFIX):
        raise ValueError(
            "remote_status_json Artifact id must start with "
            f"{REMOTE_STATUS_JSON_ARTIFACT_ID_PREFIX}: {artifact.id}"
        )

    if not artifact.uri.startswith(GENERATED_REMOTE_STATUS_JSON_URI_PREFIX):
        return

    artifact_origin = artifact.metadata.get("artifact_origin")
    if artifact_origin != "generated":
        raise ValueError(
            "generated remote_status_json Artifact metadata must include "
            f"artifact_origin='generated': {artifact.id}"
        )


def _remote_status_json_entries(
    artifacts: list[Artifact],
    remote_statuses: list[RemoteStatusArtifact],
    artifact_entries_by_id: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    remote_status_refs_by_artifact_id = {
        artifact_ref: remote_status.id
        for remote_status in remote_statuses
        for artifact_ref in remote_status.artifact_refs
    }
    entries: list[dict[str, Any]] = []
    for artifact in artifacts:
        if artifact.artifact_kind != ArtifactKind.REMOTE_STATUS_JSON:
            continue
        entry = dict(artifact_entries_by_id[artifact.id])
        remote_status_ref = (
            artifact.metadata.get("remote_status_ref")
            or remote_status_refs_by_artifact_id.get(artifact.id)
        )
        if remote_status_ref:
            entry["remote_status_ref"] = remote_status_ref
        entries.append(entry)
    return sorted(entries, key=lambda entry: entry["id"])


def _option_set_entry(option_set: DecisionOptionSet) -> dict[str, Any]:
    return {
        "id": option_set.id,
        "mission_id": option_set.mission_id,
        "generated_at": option_set.generated_at,
        "input_refs": sorted(option_set.input_refs),
        "option_ids": sorted(option.id for option in option_set.options),
        "artifact_refs": sorted(option_set.artifact_refs),
    }


def _skill_run_entry(skill_run: SkillRunRecord) -> dict[str, Any]:
    return {
        "id": skill_run.id,
        "mission_id": skill_run.mission_id,
        "skill_id": skill_run.skill_id,
        "skill_version": skill_run.skill_version,
        "activation_decision": skill_run.activation_decision,
        "input_refs": sorted(skill_run.input_refs),
        "output_refs": sorted(skill_run.output_refs),
        "artifact_refs": sorted(skill_run.artifact_refs),
    }


def _case_replay_entries(
    *,
    remote_statuses: list[RemoteStatusArtifact],
    option_sets: list[DecisionOptionSet],
    skill_runs: list[SkillRunRecord],
    separation_events: list[TeamSeparationEvent],
) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for remote_status in remote_statuses:
        related_option_sets = [
            option_set for option_set in option_sets if remote_status.id in option_set.input_refs
        ]
        related_separation_events = [
            event
            for event in separation_events
            if remote_status.id in event.evidence_refs
            or any(ref in remote_status.artifact_refs for ref in event.evidence_refs)
        ]
        related_skill_runs = [
            skill_run
            for skill_run in skill_runs
            if _has_any_ref(skill_run, [remote_status.id, *remote_status.artifact_refs])
        ]
        if not related_option_sets and not related_skill_runs and not related_separation_events:
            continue

        entries.append(
            {
                "remote_status_ref": remote_status.id,
                "artifact_refs": sorted(remote_status.artifact_refs),
                "decision_option_set_refs": [node.id for node in related_option_sets],
                "skill_run_refs": [node.id for node in related_skill_runs],
                "team_separation_event_refs": [node.id for node in related_separation_events],
            }
        )
    return sorted(entries, key=lambda entry: entry["remote_status_ref"])


def _has_any_ref(skill_run: SkillRunRecord, refs: list[str]) -> bool:
    linked_refs = (
        set(skill_run.input_refs) | set(skill_run.output_refs) | set(skill_run.artifact_refs)
    )
    return not linked_refs.isdisjoint(refs)


def _phase1_adapter_evidence_entries(
    *,
    artifacts: list[Artifact],
    facts: list[ObservedFact],
    measurements: list[DerivedMeasurement],
) -> list[dict[str, Any]]:
    phase1_artifacts = [artifact for artifact in artifacts if _is_phase1_adapter_artifact(artifact)]
    phase1_artifact_ids = {artifact.id for artifact in phase1_artifacts}
    incident_ids = sorted(
        {
            incident_id
            for artifact in phase1_artifacts
            if (incident_id := _phase1_incident_id_for_artifact(artifact))
        }
    )

    entries: list[dict[str, Any]] = []
    for incident_id in incident_ids:
        incident_artifacts = [
            artifact
            for artifact in phase1_artifacts
            if _phase1_incident_id_for_artifact(artifact) == incident_id
        ]
        incident_artifact_ids = {artifact.id for artifact in incident_artifacts}
        related_facts = [
            fact for fact in facts if _phase1_node_refs(fact) & incident_artifact_ids
        ]
        related_measurements = [
            measurement
            for measurement in measurements
            if _phase1_node_refs(measurement) & incident_artifact_ids
        ]
        artifact_refs = sorted(
            set().union(
                incident_artifact_ids,
                *(set(fact.artifact_refs) for fact in related_facts),
                *(set(measurement.artifact_refs) for measurement in related_measurements),
            )
            & phase1_artifact_ids
        )

        entries.append(
            {
                "incident_id": incident_id,
                "incident_package_artifact_refs": sorted(
                    artifact.id
                    for artifact in incident_artifacts
                    if artifact.artifact_kind == ArtifactKind.INCIDENT_PACKAGE
                ),
                "package_artifact_refs": sorted(
                    artifact.id
                    for artifact in incident_artifacts
                    if artifact.artifact_kind
                    in {
                        ArtifactKind.INCIDENT_PACKAGE,
                        ArtifactKind.RAW_LOG,
                        ArtifactKind.SEGMENT_CAPSULE,
                    }
                ),
                "fact_ids": [fact.id for fact in related_facts],
                "measurement_metrics": [
                    _phase1_measurement_metric_entry(measurement)
                    for measurement in related_measurements
                ],
                "artifact_refs": artifact_refs,
            }
        )
    return entries


def _is_phase1_adapter_artifact(artifact: Artifact) -> bool:
    return (
        artifact.id.startswith("artifact.phase1_")
        or artifact.metadata.get("phase") == "phase1"
    )


def _phase1_incident_id_for_artifact(artifact: Artifact) -> str | None:
    incident_id = artifact.metadata.get("incident_id")
    if isinstance(incident_id, str) and incident_id:
        return incident_id
    if artifact.id.startswith("artifact.phase1_"):
        return artifact.id.rsplit(".", 1)[-1]
    return None


def _phase1_node_refs(node: ObservedFact | DerivedMeasurement) -> set[str]:
    refs = set(node.artifact_refs)
    if isinstance(node, ObservedFact):
        refs.update(node.evidence)
    if isinstance(node, DerivedMeasurement):
        refs.update(node.derived_from)
    return refs


def _phase1_measurement_metric_entry(measurement: DerivedMeasurement) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "id": measurement.id,
        "metric": measurement.metric,
        "value": measurement.value,
        "artifact_refs": sorted(measurement.artifact_refs),
    }
    if measurement.unit:
        entry["unit"] = measurement.unit
    return entry


def _nodes_of_type(nodes: list[BrainNode], model: type[Any]) -> list[Any]:
    return [node for node in nodes if isinstance(node, model)]
