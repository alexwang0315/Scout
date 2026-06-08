from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from phase2_brain_ingest import ingest_brain_node
from phase2_brain_models import (
    Artifact,
    ArtifactKind,
    BrainNode,
    BrainNodeType,
    ConfidenceLevel,
    DerivedMeasurement,
    ObservedFact,
)
from phase2_brain_store import BrainFileStore
from phase2_refs import classify_phase2_ref, Phase2RefKind
from phase2_store_utils import id_token
from phase2_writeback_policy import automatic_write_allowed
from safety_models import IncidentPackage


class Phase1Phase2AdapterError(ValueError):
    pass


@dataclass
class Phase1AdapterOutput:
    artifacts: list[Artifact] = field(default_factory=list)
    observed_facts: list[ObservedFact] = field(default_factory=list)
    derived_measurements: list[DerivedMeasurement] = field(default_factory=list)

    @property
    def nodes(self) -> list[BrainNode]:
        return [*self.artifacts, *self.observed_facts, *self.derived_measurements]


def load_phase1_incident_package(path: Path | str) -> IncidentPackage:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return IncidentPackage.model_validate(payload)


def adapt_phase1_incident_package(
    package: IncidentPackage,
    *,
    source_uri: str | None = None,
    mission_id: str | None = None,
) -> Phase1AdapterOutput:
    incident_token = id_token(package.incident_id)
    triggered_at = _timestamp(package.triggered_at)
    summary = package.ai_summary_input or {}
    event = summary.get("event") or package.trigger_event.model_dump(mode="json")
    raw_window = summary.get("raw_window") or {}
    route_evidence = summary.get("route_evidence") or {}
    map_evidence = summary.get("map_evidence") or {}
    segment_capsules = summary.get("segment_capsules") or {}
    checkpoint_evidence = summary.get("checkpoint_evidence") or {}
    ack_evidence = summary.get("ack_evidence") or {}

    incident_artifact = Artifact(
        id=f"artifact.phase1_incident.{incident_token}",
        mission_id=mission_id,
        artifact_kind=ArtifactKind.INCIDENT_PACKAGE,
        uri=source_uri or f"phase1://incident/{package.incident_id}",
        media_type="application/json",
        captured_at=triggered_at,
        metadata={
            "phase": "phase1",
            "incident_id": package.incident_id,
            "trigger_level": package.trigger_level.value,
            "triggered_at": package.triggered_at,
        },
    )
    raw_window_artifact = Artifact(
        id=f"artifact.phase1_raw_window.{incident_token}",
        mission_id=mission_id,
        artifact_kind=ArtifactKind.RAW_LOG,
        uri=f"phase1://incident/{package.incident_id}/raw-window",
        media_type="application/json",
        captured_at=triggered_at,
        metadata={
            "start": package.raw_window_start,
            "end": package.raw_window_end,
            "sample_count": len(package.raw_samples),
        },
    )
    summary_artifact = Artifact(
        id=f"artifact.phase1_summary.{incident_token}",
        mission_id=mission_id,
        artifact_kind=ArtifactKind.OTHER,
        uri=f"phase1://incident/{package.incident_id}/ai-summary-input",
        media_type="application/json",
        captured_at=triggered_at,
        metadata={"sections": sorted(summary.keys())},
    )

    artifacts = [incident_artifact, raw_window_artifact, summary_artifact]
    route_artifact = _optional_artifact(
        artifact_id=f"artifact.phase1_route_evidence.{incident_token}",
        mission_id=mission_id,
        uri=f"phase1://incident/{package.incident_id}/route-evidence",
        captured_at=triggered_at,
        metadata=route_evidence,
    )
    map_artifact = _optional_artifact(
        artifact_id=f"artifact.phase1_map_evidence.{incident_token}",
        mission_id=mission_id,
        uri=f"phase1://incident/{package.incident_id}/map-evidence",
        captured_at=triggered_at,
        metadata=map_evidence,
    )
    artifacts.extend(artifact for artifact in [route_artifact, map_artifact] if artifact is not None)

    for capsule_id in _segment_capsule_ids(package, segment_capsules):
        artifacts.append(
            Artifact(
                id=f"artifact.phase1_segment_capsule.{id_token(capsule_id)}",
                mission_id=mission_id,
                artifact_kind=ArtifactKind.SEGMENT_CAPSULE,
                uri=f"phase1://segment-capsule/{capsule_id}",
                media_type="application/json",
                captured_at=triggered_at,
                metadata={
                    "capsule_id": capsule_id,
                    "incident_id": package.incident_id,
                },
            )
        )

    common_refs = [incident_artifact.id, summary_artifact.id]
    facts = [
        ObservedFact(
            id=f"fact.phase1_trigger.{incident_token}",
            mission_id=mission_id,
            subject=f"incident.{package.incident_id}",
            predicate="triggered_event_type",
            object=event.get("event_type"),
            observed_at=triggered_at,
            evidence=common_refs,
            artifact_refs=common_refs,
            confidence=_confidence(event.get("confidence")),
        )
    ]

    for transition in package.safety_transitions:
        transition_time = _timestamp(transition.timestamp)
        facts.append(
            ObservedFact(
                id=f"fact.phase1_safety_transition.{incident_token}.{id_token(transition_time)}",
                mission_id=mission_id,
                subject=f"incident.{package.incident_id}",
                predicate="safety_transition",
                object=transition.to_level.value,
                observed_at=transition_time,
                evidence=common_refs,
                artifact_refs=common_refs,
                confidence=ConfidenceLevel.HIGH,
            )
        )

    if checkpoint_evidence:
        facts.append(
            ObservedFact(
                id=f"fact.phase1_checkpoint_state.{incident_token}",
                mission_id=mission_id,
                subject=checkpoint_evidence.get("checkpoint_id") or f"incident.{package.incident_id}",
                predicate="checkpoint_state",
                object=checkpoint_evidence.get("state"),
                observed_at=checkpoint_evidence.get("observed_at") or triggered_at,
                evidence=common_refs,
                artifact_refs=common_refs,
                confidence=ConfidenceLevel.HIGH,
            )
        )

    if ack_evidence:
        facts.append(
            ObservedFact(
                id=f"fact.phase1_ack.{incident_token}",
                mission_id=mission_id,
                subject=ack_evidence.get("actor") or f"incident.{package.incident_id}",
                predicate="acknowledged",
                object=ack_evidence.get("acknowledged"),
                observed_at=ack_evidence.get("acknowledged_at") or triggered_at,
                evidence=common_refs,
                artifact_refs=common_refs,
                confidence=ConfidenceLevel.HIGH,
            )
        )

    if map_artifact is not None and map_evidence.get("corridor"):
        corridor = map_evidence["corridor"]
        facts.append(
            ObservedFact(
                id=f"fact.phase1_corridor_state.{incident_token}",
                mission_id=mission_id,
                subject=corridor.get("corridor_id") or f"incident.{package.incident_id}",
                predicate="inside_corridor",
                object=corridor.get("inside"),
                observed_at=triggered_at,
                evidence=[map_artifact.id, incident_artifact.id],
                artifact_refs=[map_artifact.id, incident_artifact.id],
                confidence=ConfidenceLevel.HIGH,
            )
        )

    measurements = [
        DerivedMeasurement(
            id=f"measurement.phase1_raw_window_duration_seconds.{incident_token}",
            mission_id=mission_id,
            subject=f"incident.{package.incident_id}",
            metric="raw_window_duration_seconds",
            value=package.raw_window_end - package.raw_window_start,
            unit="seconds",
            derived_from=[raw_window_artifact.id, incident_artifact.id],
            artifact_refs=[raw_window_artifact.id, incident_artifact.id],
            method="raw_window_end_minus_start",
        ),
        DerivedMeasurement(
            id=f"measurement.phase1_raw_window_sample_count.{incident_token}",
            mission_id=mission_id,
            subject=f"incident.{package.incident_id}",
            metric="raw_window_sample_count",
            value=raw_window.get("sample_count", len(package.raw_samples)),
            unit="samples",
            derived_from=[raw_window_artifact.id, incident_artifact.id],
            artifact_refs=[raw_window_artifact.id, incident_artifact.id],
            method="phase1_raw_window_sample_count",
        ),
    ]

    if map_artifact is not None:
        corridor = map_evidence.get("corridor") or {}
        _append_measurement(
            measurements,
            metric="distance_from_corridor_m",
            value=corridor.get("distance_from_corridor_m"),
            unit="meters",
            method="phase1_offline_map_corridor_distance",
            subject=corridor.get("corridor_id") or f"incident.{package.incident_id}",
            incident_token=incident_token,
            mission_id=mission_id,
            artifact_refs=[map_artifact.id, incident_artifact.id],
        )
        for hazard in map_evidence.get("hazards") or []:
            _append_measurement(
                measurements,
                metric="hazard_dwell_seconds",
                value=hazard.get("dwell_seconds"),
                unit="seconds",
                method="phase1_offline_map_hazard_dwell",
                subject=hazard.get("hazard_id") or f"incident.{package.incident_id}",
                incident_token=incident_token,
                mission_id=mission_id,
                artifact_refs=[map_artifact.id, incident_artifact.id],
            )

    if route_artifact is not None:
        position = route_evidence.get("position_estimate") or {}
        _append_measurement(
            measurements,
            metric="route_progress_regression_m",
            value=position.get("route_progress_regression_m"),
            unit="meters",
            method="phase1_route_progress_regression",
            subject=f"incident.{package.incident_id}",
            incident_token=incident_token,
            mission_id=mission_id,
            artifact_refs=[route_artifact.id, incident_artifact.id],
        )
        _append_measurement(
            measurements,
            metric="route_progress_m",
            value=position.get("progress_m"),
            unit="meters",
            method="phase1_route_progress_position_estimate",
            subject=f"incident.{package.incident_id}",
            incident_token=incident_token,
            mission_id=mission_id,
            artifact_refs=[route_artifact.id, incident_artifact.id],
        )

    if checkpoint_evidence:
        _append_measurement(
            measurements,
            metric="checkpoint_delay_minutes",
            value=checkpoint_evidence.get("delay_minutes"),
            unit="minutes",
            method="phase1_checkpoint_expected_vs_observed",
            subject=checkpoint_evidence.get("checkpoint_id") or f"incident.{package.incident_id}",
            incident_token=incident_token,
            mission_id=mission_id,
            artifact_refs=common_refs,
        )

    output = Phase1AdapterOutput(
        artifacts=artifacts,
        observed_facts=facts,
        derived_measurements=measurements,
    )
    validate_phase1_adapter_output(output)
    return output


def validate_phase1_adapter_output(output: Phase1AdapterOutput) -> None:
    artifacts = {artifact.id for artifact in output.artifacts}
    node_ids: set[str] = set()

    for node in output.nodes:
        if node.id in node_ids:
            raise Phase1Phase2AdapterError(f"duplicate node id: {node.id}")
        node_ids.add(node.id)

        if isinstance(node, Artifact):
            continue
        if not isinstance(node, (ObservedFact, DerivedMeasurement)):
            raise Phase1Phase2AdapterError(
                f"{node.type.value} is not allowed in Phase 1 adapter output"
            )
        if not automatic_write_allowed(node):
            raise Phase1Phase2AdapterError(
                f"{node.type.value} must use automatic write policy"
            )

        missing = sorted(_artifact_refs_for_adapter_node(node) - artifacts)
        if missing:
            raise Phase1Phase2AdapterError(
                f"{node.id} references missing artifact refs: {', '.join(missing)}"
            )


def persist_phase1_adapter_output(
    store: BrainFileStore,
    output: Phase1AdapterOutput,
) -> list[Path]:
    validate_phase1_adapter_output(output)
    paths: list[Path] = []
    for artifact in output.artifacts:
        paths.append(store.write_node(artifact))
    for node in [*output.observed_facts, *output.derived_measurements]:
        paths.append(
            ingest_brain_node(
                store,
                node,
                automatic=True,
                strict_artifact_refs=True,
            )
        )
    return paths


def _optional_artifact(
    *,
    artifact_id: str,
    mission_id: str | None,
    uri: str,
    captured_at: str,
    metadata: dict[str, Any],
) -> Artifact | None:
    if not metadata:
        return None
    return Artifact(
        id=artifact_id,
        mission_id=mission_id,
        artifact_kind=ArtifactKind.OTHER,
        uri=uri,
        media_type="application/json",
        captured_at=captured_at,
        metadata=metadata,
    )


def _segment_capsule_ids(
    package: IncidentPackage,
    segment_capsules: dict[str, Any],
) -> list[str]:
    ids = list(package.segment_capsule_ids)
    for capsule_id in segment_capsules.get("capsule_ids") or []:
        if capsule_id not in ids:
            ids.append(capsule_id)
    return ids


def _append_measurement(
    measurements: list[DerivedMeasurement],
    *,
    metric: str,
    value: str | int | float | bool | None,
    unit: str | None,
    method: str,
    subject: str,
    incident_token: str,
    mission_id: str | None,
    artifact_refs: list[str],
) -> None:
    if value is None:
        return
    subject_token = id_token(subject)
    measurements.append(
        DerivedMeasurement(
            id=f"measurement.{metric}.{subject_token}.{incident_token}",
            mission_id=mission_id,
            subject=subject,
            metric=metric,
            value=value,
            unit=unit,
            derived_from=list(artifact_refs),
            artifact_refs=list(artifact_refs),
            method=method,
        )
    )


def _artifact_refs_for_adapter_node(node: ObservedFact | DerivedMeasurement) -> set[str]:
    refs = set(node.artifact_refs)
    if isinstance(node, ObservedFact):
        refs.update(node.evidence)
    if isinstance(node, DerivedMeasurement):
        refs.update(node.derived_from)
    return {ref for ref in refs if classify_phase2_ref(ref) == Phase2RefKind.ARTIFACT}


def _confidence(value: Any) -> ConfidenceLevel:
    if not isinstance(value, int | float):
        return ConfidenceLevel.UNKNOWN
    if value >= 0.8:
        return ConfidenceLevel.HIGH
    if value >= 0.5:
        return ConfidenceLevel.MEDIUM
    return ConfidenceLevel.LOW


def _timestamp(timestamp: float) -> str:
    return datetime.fromtimestamp(timestamp, UTC).isoformat().replace("+00:00", "Z")
