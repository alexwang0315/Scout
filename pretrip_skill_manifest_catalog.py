from __future__ import annotations

import json
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


CATALOG_VERSION = "0.1.0"


class PlanningSkillWriteScope(StrEnum):
    CANDIDATES = "pretrip.workspace.candidates"
    NORMALIZED = "pretrip.workspace.normalized"
    OUTPUTS = "pretrip.workspace.outputs"
    REVIEWS = "pretrip.workspace.reviews"
    SKILL_RUN_RECORDS = "brain.skill_run_records"


class PlanningSkillRef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ref_key: str
    ref: str
    required: bool = True


class PlanningSkillReviewRequirement(BaseModel):
    model_config = ConfigDict(extra="forbid")

    required: Literal[True] = True
    stage: Literal["before_phase1_compile", "before_brain_seed_import"] = (
        "before_phase1_compile"
    )
    reviewer_role: Literal["human_operator"] = "human_operator"
    candidate_outputs_only: Literal[True] = True


class PlanningSkillFailurePolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    on_error: Literal["record_failure", "defer"]
    retry_max_attempts: Literal[0] = 0
    degrade_to: None = None


class PlanningSkillRuntimeMutationPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    phase1_runtime_mutation_allowed: Literal[False] = False
    live_safety_endpoint_calls_allowed: Literal[False] = False
    final_mission_graph_write_allowed: Literal[False] = False
    final_risk_rule_write_allowed: Literal[False] = False
    final_recording_policy_write_allowed: Literal[False] = False


class PlanningSkillBrainWritebackPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    automatic_brain_write_allowed: Literal[False] = False
    explicit_operator_writeback_required: Literal[True] = True
    observed_fact_write_allowed: Literal[False] = False
    model_interpretation_write_allowed: Literal[False] = False
    allowed_node_types: list[Literal["SkillRunRecord"]] = Field(
        default_factory=lambda: ["SkillRunRecord"]
    )


class PlanningSkillManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    skill_id: str
    version: str = CATALOG_VERSION
    status: Literal["candidate"] = "candidate"
    description: str
    allowed_input_refs: list[PlanningSkillRef] = Field(min_length=1)
    allowed_output_refs: list[PlanningSkillRef] = Field(default_factory=list)
    allowed_write_scope: list[PlanningSkillWriteScope] = Field(default_factory=list)
    review_requirement: PlanningSkillReviewRequirement = Field(
        default_factory=PlanningSkillReviewRequirement
    )
    failure_policy: PlanningSkillFailurePolicy
    runtime_mutation_policy: PlanningSkillRuntimeMutationPolicy = Field(
        default_factory=PlanningSkillRuntimeMutationPolicy
    )
    brain_writeback_policy: PlanningSkillBrainWritebackPolicy = Field(
        default_factory=PlanningSkillBrainWritebackPolicy
    )
    raw_payloads_embedded: Literal[False] = False

    @model_validator(mode="after")
    def enforce_manifest_boundaries(self) -> "PlanningSkillManifest":
        _assert_standalone_refs(self.model_dump(mode="json"))
        if any(
            scope == PlanningSkillWriteScope.REVIEWS
            for scope in self.allowed_write_scope
        ):
            raise ValueError("planning skill manifests cannot write human review logs")
        return self


class PlanningSkillManifestCatalog(BaseModel):
    model_config = ConfigDict(extra="forbid")

    catalog_id: str
    artifact_kind: Literal["planning_skill_manifest_catalog"] = (
        "planning_skill_manifest_catalog"
    )
    project_id: str
    skill_config_manifest_ref: str
    version: str = CATALOG_VERSION
    source_project_ref: Literal["project.json"] = "project.json"
    manifests: list[PlanningSkillManifest] = Field(min_length=1)
    raw_payloads_embedded: Literal[False] = False

    @model_validator(mode="after")
    def enforce_catalog_boundaries(self) -> "PlanningSkillManifestCatalog":
        skill_ids = [manifest.skill_id for manifest in self.manifests]
        if len(skill_ids) != len(set(skill_ids)):
            raise ValueError("planning skill manifest catalog skill ids must be unique")
        _assert_standalone_refs(self.model_dump(mode="json"))
        return self

    def to_json(self) -> str:
        return json.dumps(
            self.model_dump(mode="json"),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        ) + "\n"


@dataclass(frozen=True)
class _PlanningSkillContract:
    skill_id: str
    description: str
    input_ref_keys: tuple[str, ...]
    output_ref_keys: tuple[str, ...]
    write_scope: tuple[PlanningSkillWriteScope, ...]
    failure_action: Literal["record_failure", "defer"]
    review_stage: Literal["before_phase1_compile", "before_brain_seed_import"] = (
        "before_phase1_compile"
    )


_PLANNING_SKILL_CONTRACTS: tuple[_PlanningSkillContract, ...] = (
    _PlanningSkillContract(
        skill_id="pretrip-source-ingest",
        description="Register project evidence and produce normalized candidate planning artifacts by reference.",
        input_ref_keys=("route_summary_ref", "planning_references_ref"),
        output_ref_keys=(
            "package_ref",
            "checkpoint_candidates_ref",
            "segment_candidates_ref",
            "retreat_routes_ref",
        ),
        write_scope=(
            PlanningSkillWriteScope.NORMALIZED,
            PlanningSkillWriteScope.CANDIDATES,
            PlanningSkillWriteScope.OUTPUTS,
            PlanningSkillWriteScope.SKILL_RUN_RECORDS,
        ),
        failure_action="record_failure",
    ),
    _PlanningSkillContract(
        skill_id="pretrip-cp-segment-suggest",
        description="Suggest checkpoint and segment candidate artifacts from reviewed project refs.",
        input_ref_keys=("package_ref", "route_summary_ref"),
        output_ref_keys=("checkpoint_candidates_ref", "segment_candidates_ref"),
        write_scope=(
            PlanningSkillWriteScope.CANDIDATES,
            PlanningSkillWriteScope.SKILL_RUN_RECORDS,
        ),
        failure_action="record_failure",
    ),
    _PlanningSkillContract(
        skill_id="pretrip-map-import",
        description="Import map-context refs into candidate POI, hazard, and corridor artifacts.",
        input_ref_keys=("map_context_ref",),
        output_ref_keys=("map_candidates_ref",),
        write_scope=(
            PlanningSkillWriteScope.CANDIDATES,
            PlanningSkillWriteScope.SKILL_RUN_RECORDS,
        ),
        failure_action="defer",
    ),
    _PlanningSkillContract(
        skill_id="pretrip-mission-compile",
        description="Compile reviewed planning refs into a reviewed MissionGraph artifact ref without touching live runtime.",
        input_ref_keys=("reviewed_package_ref", "human_reviews_ref"),
        output_ref_keys=("compiled_mission_graph_reviewed_ref",),
        write_scope=(
            PlanningSkillWriteScope.OUTPUTS,
            PlanningSkillWriteScope.SKILL_RUN_RECORDS,
        ),
        failure_action="defer",
    ),
    _PlanningSkillContract(
        skill_id="pretrip-brain-seed-export",
        description="Export reviewed planning evidence as candidate Brain seed nodes for explicit operator import.",
        input_ref_keys=("reviewed_package_ref", "human_reviews_ref"),
        output_ref_keys=("brain_seed_nodes_ref",),
        write_scope=(
            PlanningSkillWriteScope.OUTPUTS,
            PlanningSkillWriteScope.SKILL_RUN_RECORDS,
        ),
        failure_action="record_failure",
        review_stage="before_brain_seed_import",
    ),
)


def build_chilai_skill_manifest_catalog(
    project_root: Path | str,
) -> PlanningSkillManifestCatalog:
    root = Path(project_root)
    project = _load_json(root / "project.json")
    project_id = _required_text(project, "project_id")

    return PlanningSkillManifestCatalog(
        catalog_id=f"planning_skill_manifest_catalog.{project_id}.v0",
        project_id=project_id,
        skill_config_manifest_ref=_required_text(
            project, "skill_config_manifest_ref"
        ),
        manifests=[
            _build_manifest(project, contract)
            for contract in _PLANNING_SKILL_CONTRACTS
        ],
    )


def _build_manifest(
    project: dict[str, Any], contract: _PlanningSkillContract
) -> PlanningSkillManifest:
    return PlanningSkillManifest(
        skill_id=contract.skill_id,
        description=contract.description,
        allowed_input_refs=[
            PlanningSkillRef(ref_key=key, ref=_required_text(project, key))
            for key in contract.input_ref_keys
        ],
        allowed_output_refs=[
            PlanningSkillRef(ref_key=key, ref=_required_text(project, key))
            for key in contract.output_ref_keys
        ],
        allowed_write_scope=list(contract.write_scope),
        review_requirement=PlanningSkillReviewRequirement(stage=contract.review_stage),
        failure_policy=PlanningSkillFailurePolicy(on_error=contract.failure_action),
    )


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return payload


def _required_text(project: dict[str, Any], key: str) -> str:
    value = project.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"project refs require non-empty {key}")
    return value


def _assert_standalone_refs(payload: Any) -> None:
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    forbidden_fragments = [
        "<trkpt",
        '"coordinates"',
        "candidate_tiles",
        '"source_artifacts"',
        '"checkpoint_candidates"',
        '"segment_candidates"',
        "catographydata",
        "PdrSample",
        ".gpx",
        ".grd",
        ".hdr",
        "incident_samples",
        "raw_samples",
        "IncidentPackage",
        "ObservedFact",
        "observed_facts",
        "tel:",
        "phone:",
        "email:",
        "+886",
    ]
    for fragment in forbidden_fragments:
        if fragment in serialized:
            raise ValueError(
                "planning skill manifest catalog contains forbidden raw payload "
                f"fragment: {fragment}"
            )
