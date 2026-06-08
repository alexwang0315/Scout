from __future__ import annotations

import json
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class AfterActionFindingKind(StrEnum):
    DETERMINISTIC_FINDING = "deterministic_finding"
    REVIEWER_NOTE = "reviewer_note"
    MODEL_SUGGESTION = "model_suggestion"


class AfterActionEvidenceKind(StrEnum):
    SOURCE_ROUTE = "source_route"
    CHECKPOINT = "checkpoint"
    SEGMENT_CAPSULE = "segment_capsule"
    INCIDENT_PACKAGE = "incident_package"
    MAP_EVIDENCE = "map_evidence"
    BRAIN_NODE = "brain_node"


class AfterActionBrainNodeKind(StrEnum):
    DERIVED_MEASUREMENT = "DerivedMeasurement"
    HUMAN_REVIEW = "HumanReview"
    MODEL_INTERPRETATION = "ModelInterpretation"
    DECISION_OPTION_SET = "DecisionOptionSet"


class AfterActionEvidenceRef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ref_id: str
    evidence_kind: AfterActionEvidenceKind
    source_path: str
    source_id: str
    summary: str
    brain_node_kind: AfterActionBrainNodeKind | None = None
    raw_payload_embedded: Literal[False] = False

    @model_validator(mode="after")
    def enforce_brain_ref_shape(self) -> "AfterActionEvidenceRef":
        if self.evidence_kind == AfterActionEvidenceKind.BRAIN_NODE and self.brain_node_kind is None:
            raise ValueError("brain_node evidence refs must include brain_node_kind")
        if self.brain_node_kind is not None and self.evidence_kind != AfterActionEvidenceKind.BRAIN_NODE:
            raise ValueError("brain_node_kind is only valid for brain_node refs")
        return self


class AfterActionNextPlanCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    candidate_id: str
    finding_kind: AfterActionFindingKind
    target_pretrip_candidate_kind: Literal[
        "checkpoint_candidate",
        "segment_policy_candidate",
        "map_corridor_candidate",
        "timing_calibration_candidate",
    ]
    title: str
    summary: str
    evidence_refs: list[AfterActionEvidenceRef] = Field(default_factory=list, min_length=1)
    candidate_only: Literal[True] = True
    human_review_required: Literal[True] = True
    review_state: Literal["proposed"] = "proposed"
    future_mission_graph_compile: Literal["blocked_until_human_review"] = (
        "blocked_until_human_review"
    )
    observed_fact_writeback_allowed: Literal[False] = False
    historical_evidence_mutation_allowed: Literal[False] = False


class AfterActionNextPlanCandidateExport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_id: str
    artifact_kind: Literal["after_action_next_plan_candidates"] = (
        "after_action_next_plan_candidates"
    )
    project_id: str
    source_case_id: str
    status: Literal["candidate_only"] = "candidate_only"
    policy_version: str = "0.1.0"
    source_refs: list[str]
    candidates: list[AfterActionNextPlanCandidate]
    counts: dict[str, int]
    raw_payloads_embedded: Literal[False] = False
    observed_fact_writeback_allowed: Literal[False] = False
    historical_evidence_mutation_allowed: Literal[False] = False
    notes: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def enforce_export_boundary(self) -> "AfterActionNextPlanCandidateExport":
        _assert_no_raw_samples(self.model_dump(mode="json"))
        return self

    def to_json(self) -> str:
        return json.dumps(
            self.model_dump(mode="json"),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        ) + "\n"


def build_scout_260512_after_action_next_plan_candidates(
    root: Path | str,
    *,
    project_id: str = "chilai_nanhua_day1",
) -> AfterActionNextPlanCandidateExport:
    repo_root = Path(root)
    field_case_ref = "tests/fixtures/field_cases/scout_260512_golden.json"
    mission_graph_ref = "tests/fixtures/mission_graph/scout_260512_field_mission.json"
    map_context_ref = "tests/fixtures/maps/scout_260512_overpass_map_context.geojson"
    route_ref = "tests/fixtures/routes/scout_260512_field_route.gpx"
    route_progress_ref = "tests/fixtures/route_progress/scout_260512_field_config.json"

    golden = _load_json(repo_root / field_case_ref)
    mission_graph = _load_json(repo_root / mission_graph_ref)
    map_context = _load_json(repo_root / map_context_ref)

    checkpoints = {item["checkpoint_id"]: item for item in mission_graph.get("checkpoints", [])}
    segments = {item["segment_id"]: item for item in mission_graph.get("segments", [])}
    field_segments = {item["id"]: item for item in golden.get("segments", [])}
    map_properties = map_context.get("properties", {})

    transfer_segment = segments["seg_05"]
    weak_gps_segment = field_segments["watch_260512_093931"]
    map_feature_count = len(map_context.get("features", []))

    candidates = [
        AfterActionNextPlanCandidate(
            candidate_id="after_action.scout_260512.transfer_gap.checkpoint_review",
            finding_kind=AfterActionFindingKind.DETERMINISTIC_FINDING,
            target_pretrip_candidate_kind="checkpoint_candidate",
            title="Review transfer-gap checkpoint boundary",
            summary=(
                "Segment seg_05 spans the cp_05 to cp_06 recording break with only adjacent "
                "route-point indexes; keep it as a next-plan checkpoint-boundary candidate, "
                "not a compiled MissionGraph change."
            ),
            evidence_refs=[
                _route_ref(route_ref),
                _checkpoint_ref(mission_graph_ref, checkpoints["cp_05"]),
                _checkpoint_ref(mission_graph_ref, checkpoints["cp_06"]),
                _segment_capsule_ref(
                    mission_graph_ref,
                    transfer_segment["segment_id"],
                    summary=(
                        "Segment capsule ref for transfer gap; distance_m="
                        f"{transfer_segment['distance_m']}, route points "
                        f"{transfer_segment['route_point_start_index']}.."
                        f"{transfer_segment['route_point_end_index']}."
                    ),
                ),
                _brain_ref(
                    "brain.derived_measurement.scout_260512.seg_05.transfer_gap",
                    AfterActionBrainNodeKind.DERIVED_MEASUREMENT,
                    mission_graph_ref,
                    "Derived segment-distance and route-index summary for candidate export.",
                ),
            ],
        ),
        AfterActionNextPlanCandidate(
            candidate_id="after_action.scout_260512.weak_gps.recording_policy_review",
            finding_kind=AfterActionFindingKind.REVIEWER_NOTE,
            target_pretrip_candidate_kind="segment_policy_candidate",
            title="Review weak-GPS recording policy",
            summary=(
                "The second Watch segment has p90 horizontal accuracy above 20m while map "
                "corridor agreement remains high; preserve this as a reviewer-note candidate "
                "for future recording-policy tuning."
            ),
            evidence_refs=[
                _field_segment_ref(
                    field_case_ref,
                    weak_gps_segment,
                    summary=(
                        "Field segment summary only: p90 horizontal accuracy "
                        f"{weak_gps_segment['horizontal_accuracy_p90_m']}m, "
                        "map corridor agreement with hacc "
                        f"{weak_gps_segment['map_inside_corridor_with_hacc_pct']}."
                    ),
                ),
                _segment_capsule_ref(
                    mission_graph_ref,
                    "seg_06",
                    summary="First weak-GPS forest segment capsule ref for policy review.",
                ),
                _segment_capsule_ref(
                    mission_graph_ref,
                    "seg_09",
                    summary="Final weak-GPS forest segment capsule ref for policy review.",
                ),
                _brain_ref(
                    "brain.human_review.scout_260512.weak_gps_policy_note",
                    AfterActionBrainNodeKind.HUMAN_REVIEW,
                    field_case_ref,
                    "Placeholder human-review node id; no observed facts are written.",
                ),
            ],
        ),
        AfterActionNextPlanCandidate(
            candidate_id="after_action.scout_260512.map_corridor.staleness_review",
            finding_kind=AfterActionFindingKind.MODEL_SUGGESTION,
            target_pretrip_candidate_kind="map_corridor_candidate",
            title="Re-check medium-staleness map corridors",
            summary=(
                "The after-action map context is useful but marked medium staleness risk; "
                "future plans should treat reused corridor evidence as a model suggestion "
                "requiring human review."
            ),
            evidence_refs=[
                AfterActionEvidenceRef(
                    ref_id="map.scout_260512.overpass_corridors",
                    evidence_kind=AfterActionEvidenceKind.MAP_EVIDENCE,
                    source_path=map_context_ref,
                    source_id="openstreetmap_overpass",
                    summary=(
                        f"{map_feature_count} map features; source_version="
                        f"{map_properties.get('source_version')}; staleness="
                        f"{map_properties.get('known_staleness_risk')}."
                    ),
                ),
                _brain_ref(
                    "brain.model_interpretation.scout_260512.map_corridor_staleness",
                    AfterActionBrainNodeKind.MODEL_INTERPRETATION,
                    map_context_ref,
                    "Model suggestion to review reused corridors before next-plan compile.",
                ),
            ],
        ),
    ]

    source_refs = [
        field_case_ref,
        mission_graph_ref,
        map_context_ref,
        route_ref,
        route_progress_ref,
    ]
    finding_counts = {
        finding_kind.value: sum(1 for candidate in candidates if candidate.finding_kind == finding_kind)
        for finding_kind in AfterActionFindingKind
    }
    evidence_counts = {
        evidence_kind.value: sum(
            1
            for candidate in candidates
            for ref in candidate.evidence_refs
            if ref.evidence_kind == evidence_kind
        )
        for evidence_kind in AfterActionEvidenceKind
    }

    return AfterActionNextPlanCandidateExport(
        artifact_id=f"after_action_next_plan_candidates.{project_id}.scout_260512.v0",
        project_id=project_id,
        source_case_id="scout_260512_field_golden",
        source_refs=source_refs,
        candidates=candidates,
        counts={
            "candidate_count": len(candidates),
            "source_ref_count": len(source_refs),
            "evidence_ref_count": sum(len(candidate.evidence_refs) for candidate in candidates),
            "human_review_required_count": sum(
                1 for candidate in candidates if candidate.human_review_required
            ),
            "incident_package_ref_count": evidence_counts[AfterActionEvidenceKind.INCIDENT_PACKAGE],
            **finding_counts,
            **{f"{key}_ref_count": value for key, value in evidence_counts.items()},
        },
        notes=[
            "Candidate-only Phase 4 after-action export; it does not touch the after-action UI/API.",
            "Evidence refs are summaries and pointers only; raw samples and incident samples are not embedded.",
            "Deterministic findings, reviewer notes, and model suggestions all require human review before future MissionGraph compile.",
            "The scout_260512 field fixture has no incident package refs, so incident_package_ref_count is zero.",
        ],
    )


def load_after_action_next_plan_candidate_export(
    path: Path | str,
) -> AfterActionNextPlanCandidateExport:
    return AfterActionNextPlanCandidateExport.model_validate_json(
        Path(path).read_text(encoding="utf-8")
    )


def _route_ref(route_ref: str) -> AfterActionEvidenceRef:
    return AfterActionEvidenceRef(
        ref_id="route.scout_260512.field_route",
        evidence_kind=AfterActionEvidenceKind.SOURCE_ROUTE,
        source_path=route_ref,
        source_id="scout_260512_field_route.gpx",
        summary="Source route ref only; GPX track points are not embedded.",
    )


def _checkpoint_ref(source_path: str, checkpoint: dict[str, Any]) -> AfterActionEvidenceRef:
    return AfterActionEvidenceRef(
        ref_id=f"checkpoint.{checkpoint['checkpoint_id']}",
        evidence_kind=AfterActionEvidenceKind.CHECKPOINT,
        source_path=source_path,
        source_id=checkpoint["checkpoint_id"],
        summary=f"{checkpoint['name']} ({checkpoint['checkpoint_type']}) at reviewed mission coordinates.",
    )


def _field_segment_ref(
    source_path: str,
    field_segment: dict[str, Any],
    *,
    summary: str,
) -> AfterActionEvidenceRef:
    return AfterActionEvidenceRef(
        ref_id=f"field_segment.{field_segment['id']}",
        evidence_kind=AfterActionEvidenceKind.SEGMENT_CAPSULE,
        source_path=source_path,
        source_id=field_segment["id"],
        summary=summary,
    )


def _segment_capsule_ref(source_path: str, segment_id: str, *, summary: str) -> AfterActionEvidenceRef:
    return AfterActionEvidenceRef(
        ref_id=f"segment_capsule.capsule_{segment_id}",
        evidence_kind=AfterActionEvidenceKind.SEGMENT_CAPSULE,
        source_path=source_path,
        source_id=f"capsule_{segment_id}",
        summary=summary,
    )


def _brain_ref(
    source_id: str,
    brain_node_kind: AfterActionBrainNodeKind,
    source_path: str,
    summary: str,
) -> AfterActionEvidenceRef:
    return AfterActionEvidenceRef(
        ref_id=source_id,
        evidence_kind=AfterActionEvidenceKind.BRAIN_NODE,
        source_path=source_path,
        source_id=source_id,
        summary=summary,
        brain_node_kind=brain_node_kind,
    )


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _assert_no_raw_samples(payload: Any) -> None:
    forbidden_keys = {
        "raw_samples",
        "incident_samples",
        "representative_samples",
        "coordinates",
        "points",
        "features",
        "source_files",
        "observed_facts",
    }
    forbidden_fragments = {
        "<trkpt",
        '"raw_samples"',
        '"incident_samples"',
        '"representative_samples"',
        '"coordinates"',
        '"features"',
        '"ObservedFact"',
        "PdrSample/",
    }
    _walk_no_forbidden_keys(payload, forbidden_keys)
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    for fragment in forbidden_fragments:
        if fragment in serialized:
            raise ValueError(f"raw after-action payload fragment is not allowed: {fragment}")


def _walk_no_forbidden_keys(payload: Any, forbidden_keys: set[str]) -> None:
    if isinstance(payload, dict):
        for key, value in payload.items():
            if key in forbidden_keys:
                raise ValueError(f"raw after-action payload key is not allowed: {key}")
            _walk_no_forbidden_keys(value, forbidden_keys)
    elif isinstance(payload, list):
        for item in payload:
            _walk_no_forbidden_keys(item, forbidden_keys)
