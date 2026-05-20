from __future__ import annotations

import json
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class RuntimeAuditAxis(StrEnum):
    CHECKPOINT_ETA = "checkpoint_eta"
    ROUTE_PROGRESS_CORRIDOR = "route_progress_corridor"
    RETREAT_DECISION = "retreat_decision"
    SEGMENT_POLICY = "segment_policy"
    WEATHER_DAYLIGHT = "weather_daylight"
    RESOURCE_REMOTE_SUMMARY = "resource_remote_summary"
    BRAIN_SEED_RUN_RECORDS = "brain_seed_run_records"
    READINESS_VALIDATION = "readiness_validation"


class RuntimeAuditPlannedRefs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    package_ref: str
    reviewed_package_ref: str
    planned_eta_ref: str
    readiness_report_ref: str
    plan_validation_ref: str
    route_summary_ref: str
    route_comparison_ref: str
    compiled_mission_graph_ref: str
    retreat_routes_ref: str
    segment_policy_ref: str
    weather_daylight_ref: str
    resource_plan_ref: str
    remote_contact_summary_ref: str
    brain_seed_ref: str
    planning_skill_audit_ref: str


class RuntimeAuditAxisSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    axis: RuntimeAuditAxis
    status: Literal["candidate_only"] = "candidate_only"
    planned_refs: list[str]
    runtime_evidence_expected: list[str]
    comparison_method: str
    planned_item_count: int = Field(ge=0)
    observed_item_count: Literal[0] = 0
    comparison_executed: Literal[False] = False
    raw_payloads_embedded: Literal[False] = False
    notes: list[str] = Field(default_factory=list)


class RuntimeAuditBoundary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    candidate_only: Literal[True] = True
    live_comparison_performed: Literal[False] = False
    observed_runtime_data_embedded: Literal[False] = False
    incident_package_imported: Literal[False] = False
    phase1_runtime_mutation_allowed: Literal[False] = False
    raw_payloads_embedded: Literal[False] = False


class PreTripRuntimeAuditManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    manifest_id: str
    artifact_kind: Literal["plan_to_runtime_audit_manifest"] = "plan_to_runtime_audit_manifest"
    project_id: str
    status: Literal["candidate_only"] = "candidate_only"
    plan_version_id: str
    planned_refs: RuntimeAuditPlannedRefs
    axes: list[RuntimeAuditAxisSpec]
    boundary: RuntimeAuditBoundary = Field(default_factory=RuntimeAuditBoundary)
    counts: dict[str, int]
    notes: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def enforce_manifest_boundary(self) -> "PreTripRuntimeAuditManifest":
        _assert_no_raw_payloads(self.model_dump(mode="json"))
        if len({axis.axis for axis in self.axes}) != len(self.axes):
            raise ValueError("runtime audit manifest axes must be unique")
        return self

    def to_json(self) -> str:
        return json.dumps(
            self.model_dump(mode="json"),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        ) + "\n"


def build_chilai_runtime_audit_manifest(
    project_root: Path | str,
) -> PreTripRuntimeAuditManifest:
    root = Path(project_root)
    project = _load_json(root / "project.json")
    project_id = str(project["project_id"])
    package = _load_json(root / _required_ref(project, "reviewed_package_ref"))
    eta_plan = _load_json(root / _required_ref(project, "planned_eta_ref"))
    route_summary = _load_json(root / _required_ref(project, "route_summary_ref"))
    route_comparison = _load_json(root / _required_ref(project, "route_comparison_ref"))
    segment_policy = _load_json(root / _required_ref(project, "segment_policy_candidates_ref"))
    weather_daylight = _load_json(root / _required_ref(project, "weather_daylight_evidence_ref"))
    resource_plan = _load_json(root / _required_ref(project, "resource_plan_ref"))
    remote_summary = _load_json(root / _required_ref(project, "remote_contact_summary_ref"))
    brain_seed = _load_json(root / _required_ref(project, "brain_seed_nodes_ref"))
    skill_audit = _load_json(root / _required_ref(project, "planning_skill_audit_ref"))
    readiness = _load_json(root / _required_ref(project, "readiness_report_ref"))
    plan_validation = _load_json(root / _required_ref(project, "plan_validation_candidates_ref"))
    retreat_routes = _load_json(root / _required_ref(project, "retreat_routes_ref"))

    planned_refs = RuntimeAuditPlannedRefs(
        package_ref=_required_ref(project, "package_ref"),
        reviewed_package_ref=_required_ref(project, "reviewed_package_ref"),
        planned_eta_ref=_required_ref(project, "planned_eta_ref"),
        readiness_report_ref=_required_ref(project, "readiness_report_ref"),
        plan_validation_ref=_required_ref(project, "plan_validation_candidates_ref"),
        route_summary_ref=_required_ref(project, "route_summary_ref"),
        route_comparison_ref=_required_ref(project, "route_comparison_ref"),
        compiled_mission_graph_ref=_required_ref(project, "compiled_mission_graph_reviewed_ref"),
        retreat_routes_ref=_required_ref(project, "retreat_routes_ref"),
        segment_policy_ref=_required_ref(project, "segment_policy_candidates_ref"),
        weather_daylight_ref=_required_ref(project, "weather_daylight_evidence_ref"),
        resource_plan_ref=_required_ref(project, "resource_plan_ref"),
        remote_contact_summary_ref=_required_ref(project, "remote_contact_summary_ref"),
        brain_seed_ref=_required_ref(project, "brain_seed_nodes_ref"),
        planning_skill_audit_ref=_required_ref(project, "planning_skill_audit_ref"),
    )

    axes = [
        RuntimeAuditAxisSpec(
            axis=RuntimeAuditAxis.CHECKPOINT_ETA,
            planned_refs=[
                planned_refs.planned_eta_ref,
                _required_ref(project, "timing_measurements_ref"),
            ],
            runtime_evidence_expected=[
                "persisted checkpoint arrival/departure timestamps",
                "runtime segment timing summaries",
            ],
            comparison_method=(
                "compare planned ETA estimates with observed checkpoint timing after "
                "Phase 3 imports persisted runtime evidence"
            ),
            planned_item_count=len(eta_plan.get("estimates", [])),
        ),
        RuntimeAuditAxisSpec(
            axis=RuntimeAuditAxis.ROUTE_PROGRESS_CORRIDOR,
            planned_refs=[
                planned_refs.route_summary_ref,
                planned_refs.route_comparison_ref,
                _required_ref(project, "map_candidates_ref"),
                planned_refs.compiled_mission_graph_ref,
            ],
            runtime_evidence_expected=[
                "route-progress evaluator output",
                "map-corridor deviation evidence",
                "segment capsule route samples summarized by Phase 1",
            ],
            comparison_method=(
                "compare planned route identity and corridor candidates with persisted "
                "route-progress and corridor evidence"
            ),
            planned_item_count=int(route_summary.get("point_count", 0)),
            notes=[
                f"route_comparison_classification={route_comparison.get('classification', 'unknown')}",
            ],
        ),
        RuntimeAuditAxisSpec(
            axis=RuntimeAuditAxis.RETREAT_DECISION,
            planned_refs=[
                planned_refs.retreat_routes_ref,
                planned_refs.planned_eta_ref,
                planned_refs.reviewed_package_ref,
            ],
            runtime_evidence_expected=[
                "runtime retreat/escalation decisions",
                "turn-back checkpoint timing",
                "return-to-entry route-progress evidence",
            ],
            comparison_method=(
                "compare planned turn-back checkpoint and retreat route candidates with "
                "post-trip decision and movement evidence"
            ),
            planned_item_count=len(retreat_routes),
        ),
        RuntimeAuditAxisSpec(
            axis=RuntimeAuditAxis.SEGMENT_POLICY,
            planned_refs=[
                planned_refs.segment_policy_ref,
                planned_refs.compiled_mission_graph_ref,
            ],
            runtime_evidence_expected=[
                "runtime segment policy metadata",
                "recording-policy selections",
                "segment capsule boundaries",
            ],
            comparison_method=(
                "compare candidate segment requirements and recording policy with "
                "the policy metadata preserved by runtime artifacts"
            ),
            planned_item_count=int(
                segment_policy.get("counts", {}).get(
                    "segment_policy_candidate_count",
                    len(segment_policy.get("candidates", [])),
                )
            ),
        ),
        RuntimeAuditAxisSpec(
            axis=RuntimeAuditAxis.WEATHER_DAYLIGHT,
            planned_refs=[
                planned_refs.weather_daylight_ref,
                planned_refs.segment_policy_ref,
            ],
            runtime_evidence_expected=[
                "runtime daylight margins",
                "weather-related human reviews",
                "segment timing near dark-arrival boundaries",
            ],
            comparison_method=(
                "compare reviewed weather/daylight assumptions with actual timing "
                "and any post-trip weather/daylight review evidence"
            ),
            planned_item_count=int(project.get("weather_daylight_evidence_count", 0)),
            notes=[
                f"weather_validation_status={weather_daylight.get('validation', {}).get('validation_status', 'unknown')}",
            ],
        ),
        RuntimeAuditAxisSpec(
            axis=RuntimeAuditAxis.RESOURCE_REMOTE_SUMMARY,
            planned_refs=[
                planned_refs.resource_plan_ref,
                planned_refs.remote_contact_summary_ref,
            ],
            runtime_evidence_expected=[
                "resource status observations summarized after trip",
                "remote check-in communication evidence",
                "device/battery issue reviews",
            ],
            comparison_method=(
                "compare departure resource plan and remote-contact summary with "
                "post-trip resource and communication evidence"
            ),
            planned_item_count=(
                len(resource_plan.get("devices", []))
                + len(resource_plan.get("equipment", []))
                + int(bool(remote_summary.get("summary_id")))
            ),
        ),
        RuntimeAuditAxisSpec(
            axis=RuntimeAuditAxis.BRAIN_SEED_RUN_RECORDS,
            planned_refs=[
                planned_refs.brain_seed_ref,
                planned_refs.planning_skill_audit_ref,
            ],
            runtime_evidence_expected=[
                "Phase 2 imported planning nodes",
                "runtime SkillRunRecord nodes",
                "post-trip model interpretation and human review records",
            ],
            comparison_method=(
                "compare expected Phase 4 Brain seed/run records with Phase 2/3 "
                "records preserved after runtime import"
            ),
            planned_item_count=(
                _brain_seed_node_count(brain_seed)
                + len(skill_audit.get("records", []))
            ),
            notes=[
                f"observed_fact_count={len(brain_seed.get('observed_facts', []))}",
                f"planning_skill_run_count={len(skill_audit.get('records', []))}",
            ],
        ),
        RuntimeAuditAxisSpec(
            axis=RuntimeAuditAxis.READINESS_VALIDATION,
            planned_refs=[
                planned_refs.readiness_report_ref,
                planned_refs.plan_validation_ref,
                _required_ref(project, "skill_config_manifest_ref"),
            ],
            runtime_evidence_expected=[
                "post-trip release gate findings",
                "after-action validation findings",
                "runtime bridge import status",
            ],
            comparison_method=(
                "compare pre-trip readiness and validation candidates with later "
                "Phase 3 release/admin comparison outcomes"
            ),
            planned_item_count=(
                len(readiness.get("findings", []))
                + int(plan_validation.get("counts", {}).get("finding_candidate_count", 0))
            ),
            notes=[
                f"hard_readiness_status={readiness.get('status', 'unknown')}",
                f"plan_validation_status={plan_validation.get('status', 'unknown')}",
            ],
        ),
    ]

    return PreTripRuntimeAuditManifest(
        manifest_id=f"runtime_audit_manifest.{project_id}.v0",
        project_id=project_id,
        plan_version_id=f"{package.get('package_id', 'unknown')}:{package.get('version', 'unknown')}",
        planned_refs=planned_refs,
        axes=axes,
        counts={
            "comparison_axis_count": len(axes),
            "planned_ref_count": len(planned_refs.model_dump(mode="json")),
            "observed_item_count": 0,
            "live_comparison_count": 0,
            "raw_payload_count": 0,
        },
        notes=[
            "Fixture-first Phase 4 manifest for later Phase 3 plan-to-runtime audit.",
            "No observed runtime data, incident package payload, or Phase 1 runtime artifact is imported.",
            "Each axis records refs and expected comparison method only; comparisons are intentionally not executed in this slice.",
        ],
    )


def load_runtime_audit_manifest(path: Path | str) -> PreTripRuntimeAuditManifest:
    return PreTripRuntimeAuditManifest.model_validate_json(
        Path(path).read_text(encoding="utf-8")
    )


def _required_ref(project: dict[str, Any], key: str) -> str:
    value = project.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"project.json must include {key}")
    return value


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _brain_seed_node_count(payload: dict[str, Any]) -> int:
    node_keys = (
        "artifacts",
        "derived_measurements",
        "human_reviews",
        "model_interpretations",
        "observed_facts",
    )
    return sum(len(payload.get(key, [])) for key in node_keys)


def _assert_no_raw_payloads(payload: Any) -> None:
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    forbidden_fragments = [
        "<trkpt",
        '"coordinates"',
        "candidate_tiles",
        "source_artifacts",
        "checkpoint_candidates",
        "segment_candidates",
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
                "runtime audit manifest contains forbidden raw payload fragment: "
                f"{fragment}"
            )
