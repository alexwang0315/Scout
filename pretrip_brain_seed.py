from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from phase2_brain_models import (
    Artifact,
    ArtifactKind,
    BrainNode,
    BrainNodeType,
    DerivedMeasurement,
    HumanReview,
    ModelInterpretation,
    ObservedFact,
)
from phase2_refs import classify_phase2_ref, Phase2RefKind
from phase2_store_utils import id_token
from pretrip_models import (
    PreTripArtifactKind,
    PreTripPackage,
    PreTripPlanningReference,
    PreTripRouteGuideTimingCandidate,
    PreTripSourceArtifact,
)
from pretrip_review_models import PreTripHumanReviewLog


class PreTripBrainSeedError(ValueError):
    pass


PRETRIP_PLANNING_OUTPUT_FILES = (
    "poi_readiness_candidates.json",
    "segment_policy_candidates.json",
    "plan_validation_candidates.json",
    "weather_daylight_evidence.json",
    "contour_interpretation_candidates.json",
    "resource_plan.json",
)

PRETRIP_PLANNING_OUTPUT_GENERATED_AT = "2026-05-14T00:00:00+08:00"


@dataclass(frozen=True)
class PreTripPlanningOutputSeed:
    uri: str
    payload: dict[str, Any]


@dataclass
class PreTripBrainSeedBundle:
    artifacts: list[Artifact] = field(default_factory=list)
    human_reviews: list[HumanReview] = field(default_factory=list)
    derived_measurements: list[DerivedMeasurement] = field(default_factory=list)
    model_interpretations: list[ModelInterpretation] = field(default_factory=list)

    @property
    def observed_facts(self) -> list[ObservedFact]:
        return []

    @property
    def nodes(self) -> list[BrainNode]:
        return [
            *self.artifacts,
            *self.human_reviews,
            *self.derived_measurements,
            *self.model_interpretations,
        ]

    def model_dump(self) -> dict[str, Any]:
        return {
            "artifacts": [node.model_dump(mode="json") for node in self.artifacts],
            "human_reviews": [node.model_dump(mode="json") for node in self.human_reviews],
            "derived_measurements": [
                node.model_dump(mode="json") for node in self.derived_measurements
            ],
            "model_interpretations": [
                node.model_dump(mode="json") for node in self.model_interpretations
            ],
            "observed_facts": [],
            "nodes": [node.model_dump(mode="json") for node in self.nodes],
        }


def load_pretrip_package(path: Path | str) -> PreTripPackage:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return PreTripPackage.model_validate(payload)


def load_pretrip_review_log(path: Path | str) -> PreTripHumanReviewLog:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return PreTripHumanReviewLog.model_validate(payload)


def export_chilai_pretrip_brain_seed(
    project_dir: Path | str,
    *,
    reviewed: bool = False,
    mission_id: str | None = None,
    package_uri: str | None = None,
    review_log_uri: str | None = None,
) -> PreTripBrainSeedBundle:
    root = Path(project_dir)
    package_ref = (
        root / "outputs" / "pretrip_package.reviewed.json"
        if reviewed
        else root / "outputs" / "pretrip_package.json"
    )
    review_log_ref = root / "reviews" / "human_reviews.json"
    package = load_pretrip_package(package_ref)
    review_log = load_pretrip_review_log(review_log_ref)
    planning_outputs = _load_project_planning_outputs(root)
    return export_pretrip_brain_seed(
        package,
        review_log=review_log,
        package_uri=package_uri or package_ref.as_posix(),
        review_log_uri=review_log_uri or review_log_ref.as_posix(),
        mission_id=mission_id,
        planning_outputs=planning_outputs,
    )


def export_pretrip_brain_seed(
    package: PreTripPackage,
    *,
    review_log: PreTripHumanReviewLog | None = None,
    package_uri: str | None = None,
    review_log_uri: str | None = None,
    mission_id: str | None = None,
    planning_outputs: list[PreTripPlanningOutputSeed] | None = None,
) -> PreTripBrainSeedBundle:
    project_token = id_token(package.project_id)
    package_artifact = Artifact(
        id=f"artifact.pretrip_package.{project_token}",
        mission_id=mission_id,
        artifact_kind=ArtifactKind.OTHER,
        uri=package_uri or f"pretrip://package/{package.package_id}",
        media_type="application/json",
        metadata={
            "phase": "phase4_pretrip",
            "package_id": package.package_id,
            "project_id": package.project_id,
            "version": package.version,
            "status": package.status,
            "artifact_kind": PreTripArtifactKind.PRETRIP_PACKAGE.value,
            "pretrip_candidate_evidence_only": True,
            "reviewed_planning_material_only": package.status == "reviewed",
            "reviewed_package_is_not_departure_approval": True,
            "departure_approval_granted": False,
            "departure_gate_required_before_runtime": True,
            "phase1_runtime_mutation_allowed": False,
            "phase2_brain_writeback_allowed": False,
            "safety_api_calls_allowed": False,
            "human_review_count": len(review_log.reviews) if review_log is not None else 0,
            "review_status_source": package.metadata.get(
                "review_status_source",
                "human_review_log" if review_log and review_log.reviews else "package_status",
            ),
        },
    )

    artifacts = [
        package_artifact,
        *[
            _source_artifact_to_brain_artifact(source, mission_id=mission_id)
            for source in package.source_artifacts
        ],
        *[
            _planning_reference_to_brain_artifact(reference, mission_id=mission_id)
            for reference in package.planning_references
        ],
    ]

    review_artifact: Artifact | None = None
    if review_log is not None:
        review_artifact = Artifact(
            id=f"artifact.pretrip_review_log.{id_token(review_log.log_id)}",
            mission_id=mission_id,
            artifact_kind=ArtifactKind.OTHER,
            uri=review_log_uri or f"pretrip://review-log/{review_log.log_id}",
            media_type="application/json",
            metadata={
                "phase": "phase4_pretrip",
                "log_id": review_log.log_id,
                "review_count": len(review_log.reviews),
                "artifact_kind": "human_review_log",
                "reviewed_package_is_not_departure_approval": True,
                "departure_approval_granted": False,
                "departure_gate_required_before_runtime": True,
                "phase1_runtime_mutation_allowed": False,
                "phase2_brain_writeback_allowed": False,
            },
        )
        artifacts.append(review_artifact)

    planning_artifacts = [
        _planning_output_to_brain_artifact(
            output,
            project_id=package.project_id,
            mission_id=mission_id,
        )
        for output in (planning_outputs or [])
    ]
    artifacts.extend(planning_artifacts)

    artifact_ids = {artifact.id for artifact in artifacts}
    package_refs = [package_artifact.id]
    measurements = [
        DerivedMeasurement(
            id=f"measurement.pretrip_route_distance_m.{project_token}",
            mission_id=mission_id,
            subject=f"pretrip_project.{package.project_id}",
            metric="route_distance_m",
            value=package.route_summary.distance_m,
            unit="meters",
            derived_from=[package.route_summary.artifact_id, package_artifact.id],
            artifact_refs=[
                ref
                for ref in [package.route_summary.artifact_id, package_artifact.id]
                if ref in artifact_ids
            ],
            method="pretrip_route_summary.distance_m",
        )
    ]
    measurements.extend(
        _timing_measurements(
            package.route_guide_timing_candidates,
            package_artifact_id=package_artifact.id,
            artifact_ids=artifact_ids,
            mission_id=mission_id,
        )
    )

    human_reviews: list[HumanReview] = []
    if review_log is not None:
        review_refs = [review_artifact.id] if review_artifact is not None else package_refs
        human_reviews = [
            HumanReview(
                id=f"review.pretrip.{id_token(review.review_id)}",
                mission_id=mission_id,
                reviewer_id=review.reviewer_id,
                reviewed_ref=review.reviewed_ref,
                reviewed_at=review.reviewed_at,
                decision=review.decision,
                notes=review.notes,
                correction_refs=list(review.correction.refs) if review.correction else [],
                artifact_refs=review_refs,
            )
            for review in review_log.reviews
        ]

    bundle = PreTripBrainSeedBundle(
        artifacts=artifacts,
        human_reviews=human_reviews,
        derived_measurements=measurements,
        model_interpretations=[
            _planning_output_to_model_interpretation(
                output,
                artifact=artifact,
                package=package,
                mission_id=mission_id,
            )
            for output, artifact in zip(planning_outputs or [], planning_artifacts)
        ],
    )
    validate_pretrip_brain_seed(bundle)
    return bundle


def validate_pretrip_brain_seed(bundle: PreTripBrainSeedBundle) -> None:
    artifact_ids = {artifact.id for artifact in bundle.artifacts}
    seen: set[str] = set()
    for node in bundle.nodes:
        if node.id in seen:
            raise PreTripBrainSeedError(f"duplicate node id: {node.id}")
        seen.add(node.id)
        if isinstance(node, ObservedFact):
            raise PreTripBrainSeedError("pretrip seed export must not create ObservedFact nodes")
        missing = sorted(_artifact_refs_for_node(node) - artifact_ids)
        if missing:
            raise PreTripBrainSeedError(
                f"{node.id} references missing artifact refs: {', '.join(missing)}"
            )


def _load_project_planning_outputs(root: Path) -> list[PreTripPlanningOutputSeed]:
    outputs: list[PreTripPlanningOutputSeed] = []
    for filename in PRETRIP_PLANNING_OUTPUT_FILES:
        ref = Path("outputs") / filename
        path = root / ref
        if not path.exists():
            continue
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise PreTripBrainSeedError(f"{ref.as_posix()} must contain a JSON object")
        outputs.append(PreTripPlanningOutputSeed(uri=ref.as_posix(), payload=payload))
    return outputs


def _planning_output_to_brain_artifact(
    output: PreTripPlanningOutputSeed,
    *,
    project_id: str,
    mission_id: str | None,
) -> Artifact:
    output_name = Path(output.uri).stem
    output_id = _planning_output_identity(output, output_name)
    return Artifact(
        id=f"artifact.pretrip_output.{id_token(output_id)}",
        mission_id=mission_id,
        artifact_kind=ArtifactKind.OTHER,
        uri=output.uri,
        media_type="application/json",
        metadata={
            "phase": "phase4_pretrip",
            "project_id": project_id,
            "output_name": output_name,
            "artifact_kind": str(output.payload.get("artifact_kind", output_name)),
            "candidate_context": True,
            "not_observed_fact": True,
            "summary": _planning_output_summary(output.payload),
        },
    )


def _planning_output_to_model_interpretation(
    output: PreTripPlanningOutputSeed,
    *,
    artifact: Artifact,
    package: PreTripPackage,
    mission_id: str | None,
) -> ModelInterpretation:
    output_name = Path(output.uri).stem
    output_id = _planning_output_identity(output, output_name)
    return ModelInterpretation(
        id=f"interpretation.pretrip_output.{id_token(output_id)}",
        mission_id=mission_id,
        subject=f"pretrip_project.{package.project_id}",
        model="phase4_pretrip_planning_output",
        model_version=str(output.payload.get("policy_version", package.version)),
        claim=(
            f"{output_name} is preserved as candidate planning context only; "
            "human review is required before safety-critical use. "
            f"{_planning_output_claim_details(output.payload)}"
        ),
        input_refs=[artifact.id],
        artifact_refs=[artifact.id],
        generated_at=PRETRIP_PLANNING_OUTPUT_GENERATED_AT,
    )


def _planning_output_identity(output: PreTripPlanningOutputSeed, fallback: str) -> str:
    for key in ("artifact_id", "evidence_id", "plan_id"):
        value = output.payload.get(key)
        if isinstance(value, str) and value:
            return value
    return fallback


def _planning_output_summary(payload: dict[str, Any]) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    for key in (
        "artifact_id",
        "evidence_id",
        "artifact_kind",
        "status",
        "policy_version",
        "project_id",
    ):
        value = payload.get(key)
        if value is not None:
            summary[key] = value
    counts = payload.get("counts")
    if isinstance(counts, dict):
        summary["counts"] = counts
    for key in ("candidates", "findings", "devices", "equipment"):
        value = payload.get(key)
        if isinstance(value, list):
            summary[f"{key}_count"] = len(value)
    return summary


def _planning_output_claim_details(payload: dict[str, Any]) -> str:
    summary = _planning_output_summary(payload)
    details: list[str] = []
    counts = summary.get("counts")
    if isinstance(counts, dict):
        details.extend(f"{key}={value}" for key, value in sorted(counts.items()))
    for key in ("candidates_count", "findings_count", "devices_count", "equipment_count"):
        value = summary.get(key)
        if value is not None:
            details.append(f"{key}={value}")
    if not details:
        status = summary.get("status", "candidate_context")
        details.append(f"status={status}")
    return "; ".join(details)


def _source_artifact_to_brain_artifact(
    source: PreTripSourceArtifact,
    *,
    mission_id: str | None,
) -> Artifact:
    return Artifact(
        id=source.artifact_id,
        mission_id=mission_id,
        artifact_kind=_artifact_kind(source.kind),
        uri=source.uri,
        media_type=source.media_type,
        sha256=source.sha256,
        captured_at=source.provenance.captured_at,
        metadata={
            **source.metadata,
            "phase": "phase4_pretrip",
            "pretrip_kind": source.kind.value,
            "size_bytes": source.size_bytes,
            "provenance": source.provenance.model_dump(mode="json"),
        },
    )


def _planning_reference_to_brain_artifact(
    reference: PreTripPlanningReference,
    *,
    mission_id: str | None,
) -> Artifact:
    return Artifact(
        id=f"artifact.pretrip_reference.{id_token(reference.reference_id)}",
        mission_id=mission_id,
        artifact_kind=ArtifactKind.OTHER,
        uri=reference.uri,
        media_type="text/html",
        metadata={
            "phase": "phase4_pretrip",
            "reference_id": reference.reference_id,
            "title": reference.title,
            "reference_type": reference.reference_type,
            "scout_meaning": reference.scout_meaning,
            "artifact_treatment": list(reference.artifact_treatment),
            "not_observed_fact": reference.not_observed_fact,
            "supported_primitives": list(reference.supported_primitives),
            "notes": reference.notes,
        },
    )


def _timing_measurements(
    candidates: list[PreTripRouteGuideTimingCandidate],
    *,
    package_artifact_id: str,
    artifact_ids: set[str],
    mission_id: str | None,
) -> list[DerivedMeasurement]:
    measurements: list[DerivedMeasurement] = []
    for candidate in candidates:
        refs = [
            ref
            for ref in [*candidate.source_refs, package_artifact_id]
            if ref in artifact_ids
        ]
        if package_artifact_id not in refs:
            refs.append(package_artifact_id)
        for metric, value, unit in _candidate_timing_values(candidate):
            if value is None:
                continue
            measurements.append(
                DerivedMeasurement(
                    id=f"measurement.pretrip_{metric}.{id_token(candidate.candidate_id)}",
                    mission_id=mission_id,
                    subject=candidate.candidate_id,
                    metric=metric,
                    value=value,
                    unit=unit,
                    derived_from=list(refs),
                    artifact_refs=list(refs),
                    method=f"pretrip_route_guide_timing_candidate.{metric}",
                )
            )
    return measurements


def _candidate_timing_values(
    candidate: PreTripRouteGuideTimingCandidate,
) -> list[tuple[str, int | float | None, str | None]]:
    values: list[tuple[str, int | float | None, str | None]] = [
        (
            "route_guide_segment_time_minutes",
            candidate.route_guide_segment_time_minutes,
            "minutes",
        ),
        (
            "route_guide_return_time_minutes",
            candidate.route_guide_return_time_minutes,
            "minutes",
        ),
        (
            "route_guide_ascent_time_minutes",
            candidate.route_guide_ascent_time_minutes,
            "minutes",
        ),
        (
            "route_guide_descent_time_minutes",
            candidate.route_guide_descent_time_minutes,
            "minutes",
        ),
        (
            "personal_route_guide_multiplier",
            candidate.personal_route_guide_multiplier,
            "multiplier",
        ),
        (
            "team_route_guide_multiplier",
            candidate.team_route_guide_multiplier,
            "multiplier",
        ),
        ("dark_arrival_margin_minutes", candidate.dark_arrival_margin_minutes, "minutes"),
    ]
    if candidate.fixed_rest_minutes > 0:
        values.append(("fixed_rest_minutes", candidate.fixed_rest_minutes, "minutes"))
    if candidate.conservative_long_day_adjustment != 1.0:
        values.append(
            (
                "conservative_long_day_adjustment",
                candidate.conservative_long_day_adjustment,
                "multiplier",
            )
        )
    return values


def _artifact_kind(kind: PreTripArtifactKind) -> ArtifactKind:
    if kind == PreTripArtifactKind.GPX:
        return ArtifactKind.GPX
    if kind == PreTripArtifactKind.PHOTO:
        return ArtifactKind.PHOTO
    if kind == PreTripArtifactKind.PLANNING_REFERENCES:
        return ArtifactKind.OTHER
    return ArtifactKind.OTHER


def _artifact_refs_for_node(node: BrainNode) -> set[str]:
    refs = set(node.artifact_refs)
    if isinstance(node, DerivedMeasurement):
        refs.update(node.derived_from)
    if isinstance(node, ModelInterpretation):
        refs.update(node.input_refs)
    return {ref for ref in refs if classify_phase2_ref(ref) == Phase2RefKind.ARTIFACT}
