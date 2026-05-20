from __future__ import annotations

import json
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from pretrip_models import PreTripPackage
from pretrip_readiness import evaluate_pretrip_readiness, load_skill_config_manifest


class PlanValidationSeverity(StrEnum):
    WARNING = "warning"
    BLOCKER = "blocker"


class PlanValidationFindingCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    candidate_id: str
    source_ref: str
    source_artifact_kind: str
    rule_id: str
    severity: PlanValidationSeverity
    message: str
    missing_any: list[str] = Field(default_factory=list)
    evidence_summary: dict[str, Any] = Field(default_factory=dict)
    candidate_only: bool = True
    hard_readiness_mutation_allowed: Literal[False] = False


class PreTripPlanValidationCandidateReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_id: str
    artifact_kind: Literal["plan_validation_candidates"] = "plan_validation_candidates"
    project_id: str
    status: Literal["candidate_only"] = "candidate_only"
    policy_version: str = "0.1.0"
    source_refs: list[str]
    hard_readiness_ref: str | None = None
    hard_readiness_status: str | None = None
    hard_readiness_finding_count: int = 0
    findings: list[PlanValidationFindingCandidate]
    counts: dict[str, int]
    raw_payloads_embedded: Literal[False] = False
    hard_readiness_mutation_allowed: Literal[False] = False
    notes: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def enforce_candidate_report_boundary(self) -> "PreTripPlanValidationCandidateReport":
        _assert_no_raw_payloads(self.model_dump(mode="json"))
        return self

    def to_json(self) -> str:
        return json.dumps(
            self.model_dump(mode="json"),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        ) + "\n"


def build_chilai_plan_validation_report(
    project_root: Path | str,
) -> PreTripPlanValidationCandidateReport:
    root = Path(project_root)
    project = _load_json(root / "project.json")
    package_ref = project.get("reviewed_package_ref") or project.get("package_ref")
    if not package_ref:
        raise ValueError("project.json must include reviewed_package_ref or package_ref")

    package = PreTripPackage.model_validate(_load_json(root / package_ref))
    hard_readiness = _optional_json(root, project.get("readiness_report_ref"))
    findings: list[PlanValidationFindingCandidate] = []

    findings.extend(_alternate_retreat_findings(root, project, package))
    findings.extend(_weather_daylight_findings(root, project))
    findings.extend(_resource_plan_findings(root, project))
    findings.extend(_poi_readiness_findings(root, project))
    findings.extend(_segment_policy_findings(root, project))
    findings.sort(key=lambda finding: (finding.source_artifact_kind, finding.rule_id, finding.candidate_id))

    warning_count = sum(
        1 for finding in findings if finding.severity == PlanValidationSeverity.WARNING
    )
    blocker_count = sum(
        1 for finding in findings if finding.severity == PlanValidationSeverity.BLOCKER
    )
    source_refs = _ordered_existing_refs(
        project,
        [
            "readiness_report_ref",
            "weather_daylight_evidence_ref",
            "resource_plan_ref",
            "poi_readiness_candidates_ref",
            "segment_policy_candidates_ref",
            "skill_config_manifest_ref",
            "reviewed_package_ref",
            "package_ref",
        ],
    )
    return PreTripPlanValidationCandidateReport(
        artifact_id=f"plan_validation_candidates.{package.project_id}.v0",
        project_id=package.project_id,
        source_refs=source_refs,
        hard_readiness_ref=project.get("readiness_report_ref"),
        hard_readiness_status=hard_readiness.get("status") if isinstance(hard_readiness, dict) else None,
        hard_readiness_finding_count=len(hard_readiness.get("findings", []))
        if isinstance(hard_readiness, dict)
        else 0,
        findings=findings,
        counts={
            "finding_candidate_count": len(findings),
            "warning_candidate_count": warning_count,
            "blocker_candidate_count": blocker_count,
            "source_ref_count": len(source_refs),
        },
        notes=[
            "Candidate-only Phase 4 plan validation rollup.",
            "This report summarizes existing planning gaps and does not mutate outputs/readiness_report.json.",
            "Findings contain sanitized evidence summaries only; source artifacts remain the authoritative payloads.",
        ],
    )


def load_plan_validation_candidate_report(
    path: Path | str,
) -> PreTripPlanValidationCandidateReport:
    return PreTripPlanValidationCandidateReport.model_validate_json(
        Path(path).read_text(encoding="utf-8")
    )


def _alternate_retreat_findings(
    root: Path,
    project: dict[str, Any],
    package: PreTripPackage,
) -> list[PlanValidationFindingCandidate]:
    manifest_ref = project.get("skill_config_manifest_ref")
    if not manifest_ref:
        return []
    route_plan = {
        "route_id": package.project_id,
        "route_days": _route_days_for_project(project),
        "route_kind": _route_kind_for_project(project),
        "distance_m": package.route_summary.distance_m,
        "retreat_routes": [
            candidate.model_dump(mode="json") for candidate in package.retreat_route_candidates
        ],
    }
    report = evaluate_pretrip_readiness(
        route_plan,
        skill_config_manifest=load_skill_config_manifest(root / manifest_ref),
    )
    return [
        PlanValidationFindingCandidate(
            candidate_id=f"plan_validation.{package.project_id}.{finding.rule_id}",
            source_ref=manifest_ref,
            source_artifact_kind="skill_config_manifest",
            rule_id=finding.rule_id,
            severity=PlanValidationSeverity(finding.severity),
            message=finding.message,
            missing_any=list(finding.missing_any),
            evidence_summary={
                "distance_m": round(package.route_summary.distance_m, 1),
                "retreat_route_candidate_count": len(package.retreat_route_candidates),
                "route_days": route_plan["route_days"],
                "route_kind": route_plan["route_kind"],
            },
        )
        for finding in report.findings
    ]


def _weather_daylight_findings(
    root: Path,
    project: dict[str, Any],
) -> list[PlanValidationFindingCandidate]:
    ref = project.get("weather_daylight_evidence_ref")
    payload = _optional_json(root, ref)
    if not isinstance(payload, dict):
        return []
    validation = payload.get("validation", {})
    daylight = payload.get("daylight", {})
    weather_window = payload.get("weather_window", {})
    is_placeholder = (
        validation.get("staleness") == "placeholder"
        or daylight.get("source_status") == "manual_placeholder"
        or weather_window.get("source_status") == "manual_placeholder"
    )
    if not is_placeholder:
        return []
    return [
        PlanValidationFindingCandidate(
            candidate_id=f"plan_validation.{payload.get('project_id', 'unknown')}.weather_daylight_placeholder",
            source_ref=str(ref),
            source_artifact_kind="weather_daylight_evidence",
            rule_id="weather_daylight_placeholder_requires_review",
            severity=PlanValidationSeverity.WARNING,
            message="Weather/daylight evidence is placeholder-only and needs review before go/no-go planning.",
            missing_any=["reviewed_weather_window", "reviewed_daylight_window"],
            evidence_summary={
                "validation_status": validation.get("validation_status"),
                "confidence": validation.get("confidence"),
                "staleness": validation.get("staleness"),
                "daylight_source_status": daylight.get("source_status"),
                "weather_source_status": weather_window.get("source_status"),
                "human_review_required": payload.get("human_review_required"),
                "authoritative_weather_computed": payload.get("authoritative_weather_computed"),
                "external_api_calls_made": payload.get("external_api_calls_made"),
            },
        )
    ]


def _resource_plan_findings(
    root: Path,
    project: dict[str, Any],
) -> list[PlanValidationFindingCandidate]:
    ref = project.get("resource_plan_ref")
    payload = _optional_json(root, ref)
    if not isinstance(payload, dict):
        return []
    context = payload.get("departure_readiness_context", {})
    findings: list[PlanValidationFindingCandidate] = []
    for severity, key in (
        (PlanValidationSeverity.WARNING, "warning_candidates"),
        (PlanValidationSeverity.BLOCKER, "blocker_candidates"),
    ):
        for index, message in enumerate(context.get(key, []), start=1):
            findings.append(
                PlanValidationFindingCandidate(
                    candidate_id=(
                        f"plan_validation.{payload.get('project_id', 'unknown')}"
                        f".resource_plan.{key}.{index:02d}"
                    ),
                    source_ref=str(ref),
                    source_artifact_kind="resource_plan",
                    rule_id=f"resource_plan_{key.rstrip('s')}",
                    severity=severity,
                    message=str(message),
                    evidence_summary={
                        "device_count": len(payload.get("devices", [])),
                        "equipment_count": len(payload.get("equipment", [])),
                        "hard_readiness_mutation_allowed": context.get(
                            "hard_readiness_mutation_allowed"
                        ),
                        "blocks_existing_eta_or_readiness": context.get(
                            "blocks_existing_eta_or_readiness"
                        ),
                    },
                )
            )
    return findings


def _poi_readiness_findings(
    root: Path,
    project: dict[str, Any],
) -> list[PlanValidationFindingCandidate]:
    ref = project.get("poi_readiness_candidates_ref")
    payload = _optional_json(root, ref)
    if not isinstance(payload, dict):
        return []
    findings = []
    for item in payload.get("findings", []):
        category = str(item.get("category", "unknown"))
        evidence = item.get("evidence", {})
        findings.append(
            PlanValidationFindingCandidate(
                candidate_id=f"plan_validation.{payload.get('project_id', 'unknown')}.poi.{category}",
                source_ref=str(ref),
                source_artifact_kind="poi_readiness_candidates",
                rule_id=f"poi_readiness_missing_{category}",
                severity=PlanValidationSeverity(item.get("severity")),
                message=str(item.get("message")),
                missing_any=list(item.get("missing_any", [])),
                evidence_summary={
                    "category": category,
                    "present_categories": sorted(evidence.get("present_categories", [])),
                    "candidate_only": item.get("candidate_only"),
                },
            )
        )
    return findings


def _segment_policy_findings(
    root: Path,
    project: dict[str, Any],
) -> list[PlanValidationFindingCandidate]:
    ref = project.get("segment_policy_candidates_ref")
    payload = _optional_json(root, ref)
    if not isinstance(payload, dict):
        return []
    counts = payload.get("counts", {})
    findings: list[PlanValidationFindingCandidate] = []
    human_review_required_count = int(counts.get("human_review_required_count") or 0)
    if human_review_required_count:
        findings.append(
            PlanValidationFindingCandidate(
                candidate_id=(
                    f"plan_validation.{payload.get('project_id', 'unknown')}"
                    ".segment_policy.human_review_required"
                ),
                source_ref=str(ref),
                source_artifact_kind="segment_policy_candidates",
                rule_id="segment_policy_candidates_require_human_review",
                severity=PlanValidationSeverity.WARNING,
                message="Segment policy candidates require human review before compile-time use.",
                missing_any=["accepted_segment_policy_reviews"],
                evidence_summary={
                    "candidate_count": counts.get("segment_policy_candidate_count"),
                    "human_review_required_count": human_review_required_count,
                    "candidate_only_count": counts.get("candidate_only_count"),
                    "compile_boundary": "candidate_only_not_runtime",
                },
            )
        )
    requires_daylight_count = int(counts.get("requires_daylight_count") or 0)
    if requires_daylight_count:
        findings.append(
            PlanValidationFindingCandidate(
                candidate_id=(
                    f"plan_validation.{payload.get('project_id', 'unknown')}"
                    ".segment_policy.daylight_review"
                ),
                source_ref=str(ref),
                source_artifact_kind="segment_policy_candidates",
                rule_id="segment_policy_requires_reviewed_daylight",
                severity=PlanValidationSeverity.WARNING,
                message="Segment policies require daylight but only candidate weather/daylight evidence is present.",
                missing_any=["reviewed_daylight_window"],
                evidence_summary={
                    "candidate_count": counts.get("segment_policy_candidate_count"),
                    "requires_daylight_count": requires_daylight_count,
                    "retreat_available_count": counts.get("retreat_available_count"),
                    "signal_expected_count": counts.get("signal_expected_count"),
                },
            )
        )
    return findings


def _route_days_for_project(project: dict[str, Any]) -> int:
    if project.get("project_id") == "chilai_nanhua_day1":
        return 2
    return int(project.get("route_days") or 1)


def _route_kind_for_project(project: dict[str, Any]) -> str:
    if project.get("project_id") == "chilai_nanhua_day1":
        return "traverse"
    return str(project.get("route_kind") or "out_and_back")


def _ordered_existing_refs(project: dict[str, Any], keys: list[str]) -> list[str]:
    refs: list[str] = []
    for key in keys:
        ref = project.get(key)
        if ref and ref not in refs:
            refs.append(ref)
    return refs


def _optional_json(root: Path, ref: str | None) -> Any | None:
    if not ref:
        return None
    path = root / ref
    if not path.exists():
        return None
    return _load_json(path)


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _assert_no_raw_payloads(payload: Any) -> None:
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    forbidden_fragments = [
        "<trkpt",
        "\"coordinates\"",
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
        "tel:",
        "phone:",
        "email:",
        "+886",
    ]
    for fragment in forbidden_fragments:
        if fragment in serialized:
            raise ValueError(f"plan validation report contains forbidden raw payload fragment: {fragment}")
