from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from pydantic import BaseModel, ConfigDict, Field

from phase2_brain_models import SkillRunRecord
from phase2_store_utils import id_token
from skill_registry_models import SkillManifest
from skill_runtime import record_mock_skill_run


CHILAI_PRETRIP_PROJECT_ROOT = (
    Path(__file__).resolve().parent
    / "tests"
    / "fixtures"
    / "pretrip"
    / "projects"
    / "chilai_nanhua_day1"
)

PLANNING_AUDIT_VERSION = "0.1.0"
PLANNING_AUDIT_STARTED_AT = "2026-05-14T00:00:00+08:00"


class PreTripSkillAuditBundle(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: str
    project_ref: str
    records: list[SkillRunRecord] = Field(default_factory=list)


@dataclass(frozen=True)
class _PlanningSkillStep:
    skill_id: str
    input_ref_keys: tuple[str, ...]
    output_ref_keys: tuple[str, ...]
    required_capabilities: tuple[str, ...]
    failure_policy: Mapping[str, object]
    status_label: str


_PLANNING_SKILL_STEPS: tuple[_PlanningSkillStep, ...] = (
    _PlanningSkillStep(
        skill_id="pretrip-source-ingest",
        input_ref_keys=("route_summary_ref", "planning_references_ref"),
        output_ref_keys=(
            "package_ref",
            "checkpoint_candidates_ref",
            "segment_candidates_ref",
            "retreat_routes_ref",
        ),
        required_capabilities=("project_refs.read", "pretrip_package.write_candidate"),
        failure_policy={
            "on_error": "record_failure",
            "retry": {"max_attempts": 0, "backoff_seconds": 0},
            "degrade_to": None,
        },
        status_label="Pre-trip source ingest",
    ),
    _PlanningSkillStep(
        skill_id="pretrip-cp-segment-suggest",
        input_ref_keys=("package_ref", "route_summary_ref"),
        output_ref_keys=("checkpoint_candidates_ref", "segment_candidates_ref"),
        required_capabilities=("project_refs.read", "planning_candidates.write"),
        failure_policy={
            "on_error": "record_failure",
            "retry": {"max_attempts": 0, "backoff_seconds": 0},
            "degrade_to": None,
        },
        status_label="Pre-trip checkpoint and segment suggestion",
    ),
    _PlanningSkillStep(
        skill_id="pretrip-map-import",
        input_ref_keys=("map_context_ref",),
        output_ref_keys=("map_candidates_ref",),
        required_capabilities=("project_refs.read", "geojson.read"),
        failure_policy={
            "on_error": "defer",
            "retry": {"max_attempts": 0, "backoff_seconds": 0},
            "degrade_to": None,
        },
        status_label="Pre-trip map import",
    ),
    _PlanningSkillStep(
        skill_id="pretrip-mission-compile",
        input_ref_keys=("reviewed_package_ref", "human_reviews_ref"),
        output_ref_keys=("compiled_mission_graph_reviewed_ref",),
        required_capabilities=("project_refs.read", "mission_graph.compile_candidate"),
        failure_policy={
            "on_error": "defer",
            "retry": {"max_attempts": 0, "backoff_seconds": 0},
            "degrade_to": None,
        },
        status_label="Pre-trip mission compile",
    ),
    _PlanningSkillStep(
        skill_id="pretrip-brain-seed-export",
        input_ref_keys=("reviewed_package_ref", "human_reviews_ref"),
        output_ref_keys=("brain_seed_nodes_ref",),
        required_capabilities=("project_refs.read", "brain_seed.export_candidate"),
        failure_policy={
            "on_error": "record_failure",
            "retry": {"max_attempts": 0, "backoff_seconds": 0},
            "degrade_to": None,
        },
        status_label="Pre-trip Brain seed export",
    ),
)


def load_pretrip_project_refs(project_json_path: Path | str) -> dict[str, Any]:
    return json.loads(Path(project_json_path).read_text())


def export_chilai_pretrip_skill_audit_bundle(
    fixture_root: Path | str = CHILAI_PRETRIP_PROJECT_ROOT,
) -> PreTripSkillAuditBundle:
    root = Path(fixture_root)
    return build_pretrip_skill_audit_bundle(
        load_pretrip_project_refs(root / "project.json"),
        project_ref="project.json",
    )


def build_pretrip_skill_audit_bundle(
    project_refs: Mapping[str, Any],
    *,
    project_ref: str,
    mission_id: str | None = None,
) -> PreTripSkillAuditBundle:
    project_id = _required_text(project_refs, "project_id")
    records = [
        _record_planning_skill_step(
            project_refs,
            project_id=project_id,
            project_ref=project_ref,
            step=step,
            mission_id=mission_id,
            sequence=sequence,
        )
        for sequence, step in enumerate(_PLANNING_SKILL_STEPS, start=1)
    ]
    return PreTripSkillAuditBundle(
        project_id=project_id,
        project_ref=project_ref,
        records=records,
    )


def _record_planning_skill_step(
    project_refs: Mapping[str, Any],
    *,
    project_id: str,
    project_ref: str,
    step: _PlanningSkillStep,
    mission_id: str | None,
    sequence: int,
) -> SkillRunRecord:
    input_refs = [project_ref, *_refs_for_keys(project_refs, step.input_ref_keys)]
    output_refs = _refs_for_keys(project_refs, step.output_ref_keys)
    missing_ref_keys = _missing_ref_keys(project_refs, (*step.input_ref_keys, *step.output_ref_keys))
    activation_decision = "allow" if not missing_ref_keys else "defer"
    manifest = _planning_skill_manifest(step)
    return record_mock_skill_run(
        manifest,
        input_refs=input_refs,
        output_refs=output_refs,
        artifact_refs=[],
        preflight_results={
            "status": "passed" if not missing_ref_keys else "deferred",
            "project_ref": project_ref,
            "project_id": project_id,
            "required_project_ref_keys": [*step.input_ref_keys, *step.output_ref_keys],
            "missing_project_ref_keys": missing_ref_keys,
            "required_capabilities": list(step.required_capabilities),
            "writeback_policy": {
                "record_kind": "SkillRunRecord",
                "automatic_brain_write": False,
                "creates_observed_fact": False,
                "creates_model_interpretation": False,
            },
        },
        activation_decision=activation_decision,
        failure_policy=step.failure_policy,
        started_at=PLANNING_AUDIT_STARTED_AT,
        ended_at=PLANNING_AUDIT_STARTED_AT,
        mission_id=mission_id,
        run_id=_planning_run_id(project_id, step.skill_id, sequence),
    )


def _planning_skill_manifest(step: _PlanningSkillStep) -> SkillManifest:
    return SkillManifest.model_validate(
        {
            "id": step.skill_id,
            "version": PLANNING_AUDIT_VERSION,
            "status": "candidate",
            "type": "artifact",
            "priority": 50,
            "triggers": [
                {
                    "event": "phase4_pretrip_project_workspace_step",
                    "description": f"Audit Phase 4 planning workspace step {step.skill_id}.",
                    "required_refs": list(step.input_ref_keys),
                }
            ],
            "activation_gate": {
                "mode": "operator_approved",
                "requires_human_approval": True,
                "conditions": ["project.json refs are present"],
            },
            "noise_control": {
                "cooldown_seconds": 0,
                "dedupe_window_seconds": 0,
                "max_runs_per_mission": 1,
                "suppression_keys": ["project_id", "skill_id"],
            },
            "preflight": {
                "required_skill_ids": [],
                "required_capabilities": list(step.required_capabilities),
                "required_artifacts": list(step.input_ref_keys),
            },
            "allowed_reads": ["project.refs", "pretrip.workspace"],
            "allowed_writes": ["brain.skill_run_records"],
            "forbidden_writes": [
                "brain.observed_facts",
                "brain.model_interpretations",
                "phase1.runtime",
                "dtm.rasters",
                "map.compiler",
                "brain.seed_store",
            ],
            "output_schema": {
                "format": "brain-node",
                "node_types": ["SkillRunRecord"],
                "artifact_kinds": [],
                "required_fields": [
                    "input_refs",
                    "output_refs",
                    "preflight_results",
                    "failure_policy",
                    "activation_decision",
                ],
            },
            "failure_policy": step.failure_policy,
            "control_surface": {
                "operator_visible": True,
                "manual_run_allowed": True,
                "disable_allowed": True,
                "status_label": step.status_label,
            },
            "audit": {
                "log_inputs": True,
                "log_outputs": True,
                "log_decision": True,
                "retention": "mission_lifetime",
            },
        }
    )


def _refs_for_keys(project_refs: Mapping[str, Any], keys: tuple[str, ...]) -> list[str]:
    refs: list[str] = []
    for key in keys:
        value = project_refs.get(key)
        if isinstance(value, str) and value:
            refs.append(value)
    return refs


def _missing_ref_keys(project_refs: Mapping[str, Any], keys: tuple[str, ...]) -> list[str]:
    return [
        key
        for key in keys
        if not isinstance(project_refs.get(key), str) or not project_refs.get(key)
    ]


def _required_text(project_refs: Mapping[str, Any], key: str) -> str:
    value = project_refs.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"project refs require non-empty {key}")
    return value


def _planning_run_id(project_id: str, skill_id: str, sequence: int) -> str:
    return f"skill_run.phase4_pretrip.{id_token(project_id)}.{sequence:02d}.{skill_id}"
