from __future__ import annotations

import hashlib
import json
from collections import Counter
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


DEFAULT_CHILAI_PROJECT_REF = (
    "tests/fixtures/pretrip/projects/chilai_nanhua_day1/project.json"
)


class DepartureGateStatus(StrEnum):
    PASSED = "passed"
    HOLD = "hold"
    BLOCKED = "blocked"


class DepartureGateSeverity(StrEnum):
    WARNING = "warning"
    BLOCKER = "blocker"


class StrictDepartureGateModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DepartureGateRef(StrictDepartureGateModel):
    ref_key: str
    ref: str
    artifact_kind: str
    sha256: str
    exists: Literal[True] = True
    status: str | None = None
    summary: dict[str, Any] = Field(default_factory=dict)


class DepartureGateFinding(StrictDepartureGateModel):
    finding_id: str
    severity: DepartureGateSeverity
    rule_id: str
    message: str
    source_ref: str
    source_artifact_kind: str
    blocker_override_allowed: bool
    requires_resolution_before_departure: bool
    chinese_explanation: str
    evidence_summary: dict[str, Any] = Field(default_factory=dict)


class DepartureGateCounts(StrictDepartureGateModel):
    input_ref_count: int = Field(ge=0)
    warning_count: int = Field(ge=0)
    blocker_count: int = Field(ge=0)
    override_reason_count: int = Field(ge=0)
    unresolved_warning_count: int = Field(ge=0)
    hard_blocker_count: int = Field(ge=0)
    runtime_write_count: Literal[0] = 0
    safety_call_count: Literal[0] = 0
    phase2_writeback_count: Literal[0] = 0


class DepartureGateBoundary(StrictDepartureGateModel):
    planning_workspace_only: Literal[True] = True
    departure_approval_is_explicit: Literal[True] = True
    reviewed_package_is_not_departure_approval: Literal[True] = True
    final_mission_graph_generation_allowed: bool
    runtime_handoff_allowed: Literal[False] = False
    phase1_runtime_mutation_allowed: Literal[False] = False
    safety_api_calls_allowed: Literal[False] = False
    phase2_writeback_allowed: Literal[False] = False
    external_api_calls_made: Literal[False] = False
    raw_payloads_embedded: Literal[False] = False
    notes: list[str] = Field(default_factory=list)


class DepartureApprovalRecord(StrictDepartureGateModel):
    approval_id: str
    approval_kind: Literal["departure_approval_record"] = "departure_approval_record"
    status: DepartureGateStatus
    approval_granted: bool
    project_id: str
    profile_id: str
    profile_display_name_zh: str
    approved_by: str | None = None
    approved_at: str | None = None
    reviewed_package_ref: str
    reviewed_package_hash: str
    mission_graph_candidate_ref: str
    mission_graph_candidate_hash: str
    final_mission_graph_generation_allowed: bool
    runtime_handoff_allowed: Literal[False] = False
    unresolved_warnings: list[DepartureGateFinding] = Field(default_factory=list)
    blockers: list[DepartureGateFinding] = Field(default_factory=list)
    override_reasons: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def enforce_approval_state(self) -> "DepartureApprovalRecord":
        if self.approval_granted and self.status != DepartureGateStatus.PASSED:
            raise ValueError("approval_granted requires passed departure gate")
        if self.final_mission_graph_generation_allowed and self.status != DepartureGateStatus.PASSED:
            raise ValueError("final MissionGraph generation requires passed departure gate")
        if self.status == DepartureGateStatus.PASSED and self.blockers:
            raise ValueError("passed departure gate cannot include blockers")
        return self


class PreTripDepartureGateManifest(StrictDepartureGateModel):
    manifest_id: str
    artifact_kind: Literal["pretrip_departure_gate_manifest"] = (
        "pretrip_departure_gate_manifest"
    )
    project_id: str
    status: DepartureGateStatus
    planning_review_profile_ref: str
    route_class: str
    trip_classification_zh: str
    input_refs: list[DepartureGateRef]
    findings: list[DepartureGateFinding]
    approval: DepartureApprovalRecord
    counts: DepartureGateCounts
    boundary: DepartureGateBoundary
    notes: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def enforce_gate_boundary(self) -> "PreTripDepartureGateManifest":
        if self.status != self.approval.status:
            raise ValueError("manifest status must match approval status")
        if self.counts.input_ref_count != len(self.input_refs):
            raise ValueError("input_ref_count must match input refs")
        if self.counts.warning_count != sum(
            finding.severity == DepartureGateSeverity.WARNING
            for finding in self.findings
        ):
            raise ValueError("warning_count must match findings")
        if self.counts.blocker_count != sum(
            finding.severity == DepartureGateSeverity.BLOCKER
            for finding in self.findings
        ):
            raise ValueError("blocker_count must match findings")
        _assert_no_runtime_or_raw_payload_fragments(self.model_dump(mode="json"))
        return self

    def to_json(self) -> str:
        return json.dumps(
            self.model_dump(mode="json"),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        ) + "\n"


def build_chilai_departure_gate_manifest(
    project_root: Path | str,
    *,
    profile_id: str = "quick_review.v0",
    profile_display_name_zh: str = "快捷模式",
    route_class: str = "deep_mountain_out_and_back",
) -> PreTripDepartureGateManifest:
    project_path = _resolve_chilai_project_path(Path(project_root))
    fixture_root = project_path.parent
    project = _load_json(project_path)

    input_refs = [
        _required_ref(fixture_root, project, "reviewed_package_ref", "reviewed_pretrip_package"),
        _required_ref(
            fixture_root,
            project,
            "compiled_mission_graph_reviewed_ref",
            "reviewed_mission_graph_candidate",
        ),
        _required_ref(fixture_root, project, "readiness_report_ref", "readiness_report"),
        _required_ref(
            fixture_root,
            project,
            "plan_validation_candidates_ref",
            "plan_validation_candidates",
        ),
        _required_ref(
            fixture_root,
            project,
            "poi_readiness_candidates_ref",
            "poi_readiness_candidates",
        ),
        _required_ref(fixture_root, project, "resource_plan_ref", "resource_plan"),
        _required_ref(
            fixture_root,
            project,
            "weather_daylight_evidence_ref",
            "weather_daylight_evidence",
        ),
        _required_ref(fixture_root, project, "planned_eta_ref", "planned_eta"),
        _required_ref(fixture_root, project, "retreat_routes_ref", "retreat_routes"),
        _required_ref(
            fixture_root,
            project,
            "remote_contact_summary_ref",
            "remote_contact_summary",
        ),
    ]
    refs_by_key = {ref.ref_key: ref for ref in input_refs}

    reviewed_package = _load_json(fixture_root / project["reviewed_package_ref"])
    mission_graph_ref = refs_by_key["compiled_mission_graph_reviewed_ref"]
    package_ref = refs_by_key["reviewed_package_ref"]
    findings = _gate_findings(fixture_root, project, reviewed_package)
    severity_counts = Counter(finding.severity for finding in findings)
    hard_blocker_count = sum(
        1
        for finding in findings
        if finding.severity == DepartureGateSeverity.BLOCKER
        and not finding.blocker_override_allowed
    )
    status = _status_for(findings)
    final_generation_allowed = status == DepartureGateStatus.PASSED

    approval = DepartureApprovalRecord(
        approval_id=f"departure_approval.{project['project_id']}.{profile_id}",
        status=status,
        approval_granted=status == DepartureGateStatus.PASSED,
        project_id=project["project_id"],
        profile_id=profile_id,
        profile_display_name_zh=profile_display_name_zh,
        reviewed_package_ref=package_ref.ref,
        reviewed_package_hash=package_ref.sha256,
        mission_graph_candidate_ref=mission_graph_ref.ref,
        mission_graph_candidate_hash=mission_graph_ref.sha256,
        final_mission_graph_generation_allowed=final_generation_allowed,
        unresolved_warnings=[
            finding
            for finding in findings
            if finding.severity == DepartureGateSeverity.WARNING
        ],
        blockers=[
            finding
            for finding in findings
            if finding.severity == DepartureGateSeverity.BLOCKER
        ],
    )
    return PreTripDepartureGateManifest(
        manifest_id=f"departure_gate.{project['project_id']}.{profile_id}",
        project_id=project["project_id"],
        status=status,
        planning_review_profile_ref=profile_id,
        route_class=route_class,
        trip_classification_zh="深山原路折返",
        input_refs=input_refs,
        findings=findings,
        approval=approval,
        counts=DepartureGateCounts(
            input_ref_count=len(input_refs),
            warning_count=severity_counts[DepartureGateSeverity.WARNING],
            blocker_count=severity_counts[DepartureGateSeverity.BLOCKER],
            override_reason_count=0,
            unresolved_warning_count=severity_counts[DepartureGateSeverity.WARNING],
            hard_blocker_count=hard_blocker_count,
        ),
        boundary=DepartureGateBoundary(
            final_mission_graph_generation_allowed=final_generation_allowed,
            notes=[
                "Departure Gate / 出發關卡 evaluates reviewed planning artifacts but does not activate runtime.",
                "Reviewed Package / 已審核規劃包 remains separate from departure approval.",
                "Final MissionGraph / 最終任務圖 generation is allowed only when this gate passes.",
                "Runtime Handoff / 現場 runtime 交接 remains closed in this slice.",
            ],
        ),
        notes=[
            "Chilai-Nanhua Day 1 is treated as deep_mountain_out_and_back because return-to-entry retreat is the practical first retreat policy.",
            "Warnings remain visible even when a Quick Review profile reduces review friction.",
        ],
    )


def load_departure_gate_manifest(path: Path | str) -> PreTripDepartureGateManifest:
    return PreTripDepartureGateManifest.model_validate_json(
        Path(path).read_text(encoding="utf-8")
    )


def _gate_findings(
    fixture_root: Path,
    project: dict[str, Any],
    reviewed_package: dict[str, Any],
) -> list[DepartureGateFinding]:
    findings: list[DepartureGateFinding] = []
    if reviewed_package.get("status") != "reviewed":
        findings.append(
            _finding(
                "no_reviewed_package",
                DepartureGateSeverity.BLOCKER,
                "Reviewed package is required before Departure Gate approval.",
                project["reviewed_package_ref"],
                "reviewed_pretrip_package",
                blocker_override_allowed=False,
                chinese_explanation="缺少已審核規劃包，不能進入出發批准。",
            )
        )

    retreat_routes = _load_json(fixture_root / project["retreat_routes_ref"])
    accepted_return_retreat = any(
        route.get("review_state") == "accepted"
        and route.get("retreat_type") == "return_to_entry"
        for route in retreat_routes
        if isinstance(route, dict)
    )
    if not accepted_return_retreat:
        findings.append(
            _finding(
                "no_retreat_policy_for_required_route",
                DepartureGateSeverity.BLOCKER,
                "Deep mountain route requires an accepted return-to-entry or equivalent retreat policy.",
                project["retreat_routes_ref"],
                "retreat_routes",
                blocker_override_allowed=False,
                chinese_explanation="深山路線需要已接受的折返回入口或等效撤退策略。",
                evidence_summary={"route_class": "deep_mountain_out_and_back"},
            )
        )

    readiness = _load_json(fixture_root / project["readiness_report_ref"])
    if readiness.get("status") == "blocked":
        findings.append(
            _finding(
                "hard_readiness_blocked",
                DepartureGateSeverity.BLOCKER,
                "Hard readiness report is blocked.",
                project["readiness_report_ref"],
                "readiness_report",
                blocker_override_allowed=False,
                chinese_explanation="硬性整備報告已阻擋，不能靠覆寫略過。",
                evidence_summary={"status": readiness.get("status")},
            )
        )

    plan_validation = _load_json(fixture_root / project["plan_validation_candidates_ref"])
    for candidate in plan_validation.get("findings", []):
        severity = DepartureGateSeverity(candidate.get("severity", "warning"))
        blocker_override_allowed = severity != DepartureGateSeverity.BLOCKER
        findings.append(
            _finding(
                candidate.get("rule_id", "plan_validation_finding"),
                severity,
                candidate.get("message", "Plan validation finding requires review."),
                candidate.get("source_ref", project["plan_validation_candidates_ref"]),
                candidate.get("source_artifact_kind", "plan_validation_candidates"),
                blocker_override_allowed=blocker_override_allowed,
                chinese_explanation=(
                    "規劃驗證發現需要在出發前處理；warning 可帶理由保留，blocker 不可靜默略過。"
                ),
                evidence_summary=candidate.get("evidence_summary", {}),
            )
        )

    poi_readiness = _load_json(fixture_root / project["poi_readiness_candidates_ref"])
    for policy in poi_readiness.get("policy_candidates", []):
        if policy.get("severity") != "warning":
            continue
        findings.append(
            _finding(
                "poi_corridor_policy_warning",
                DepartureGateSeverity.WARNING,
                policy.get("message", "POI corridor policy warning."),
                project["poi_readiness_candidates_ref"],
                "poi_readiness_candidates",
                blocker_override_allowed=True,
                chinese_explanation="路徑走廊 POI 覆蓋不足只產生 warning，可由 admin 參數化距離與門檻。",
                evidence_summary={
                    "corridor_distance_m": policy.get("corridor_distance_m"),
                    "minimum_poi_count": policy.get("minimum_poi_count"),
                },
            )
        )

    return sorted(findings, key=lambda finding: (finding.severity, finding.rule_id, finding.finding_id))


def _finding(
    rule_id: str,
    severity: DepartureGateSeverity,
    message: str,
    source_ref: str,
    source_artifact_kind: str,
    *,
    blocker_override_allowed: bool,
    chinese_explanation: str,
    evidence_summary: dict[str, Any] | None = None,
) -> DepartureGateFinding:
    safe_rule_id = rule_id.replace("/", "_").replace(" ", "_")
    source_hash = hashlib.sha256(
        f"{rule_id}|{source_ref}|{source_artifact_kind}|{message}".encode("utf-8")
    ).hexdigest()[:10]
    return DepartureGateFinding(
        finding_id=f"departure_gate.{safe_rule_id}.{source_hash}",
        severity=severity,
        rule_id=rule_id,
        message=message,
        source_ref=source_ref,
        source_artifact_kind=source_artifact_kind,
        blocker_override_allowed=blocker_override_allowed,
        requires_resolution_before_departure=severity == DepartureGateSeverity.BLOCKER,
        chinese_explanation=chinese_explanation,
        evidence_summary=evidence_summary or {},
    )


def _status_for(findings: list[DepartureGateFinding]) -> DepartureGateStatus:
    if any(finding.severity == DepartureGateSeverity.BLOCKER for finding in findings):
        return DepartureGateStatus.BLOCKED
    if any(finding.severity == DepartureGateSeverity.WARNING for finding in findings):
        return DepartureGateStatus.HOLD
    return DepartureGateStatus.PASSED


def _required_ref(
    fixture_root: Path,
    project: dict[str, Any],
    ref_key: str,
    artifact_kind: str,
) -> DepartureGateRef:
    ref = project[ref_key]
    path = fixture_root / ref
    payload = _load_json(path)
    return DepartureGateRef(
        ref_key=ref_key,
        ref=ref,
        artifact_kind=artifact_kind,
        sha256=_sha256(path),
        status=payload.get("status") if isinstance(payload, dict) else None,
        summary=_summary_for(payload),
    )


def _summary_for(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {}
    summary: dict[str, Any] = {}
    for key in (
        "artifact_id",
        "artifact_kind",
        "bundle_id",
        "manifest_id",
        "package_id",
        "project_id",
        "status",
        "version",
        "plan_id",
    ):
        if key in payload:
            summary[key] = payload[key]
    if "counts" in payload and isinstance(payload["counts"], dict):
        summary["counts"] = payload["counts"]
    if "findings" in payload and isinstance(payload["findings"], list):
        summary["finding_count"] = len(payload["findings"])
    if "checkpoints" in payload and isinstance(payload["checkpoints"], list):
        summary["checkpoint_count"] = len(payload["checkpoints"])
    if "segments" in payload and isinstance(payload["segments"], list):
        summary["segment_count"] = len(payload["segments"])
    return summary


def _resolve_chilai_project_path(path: Path) -> Path:
    if path.name == "project.json":
        return path
    if (path / "project.json").exists():
        return path / "project.json"
    repo_fixture = path / DEFAULT_CHILAI_PROJECT_REF
    if repo_fixture.exists():
        return repo_fixture
    raise FileNotFoundError(f"could not find Chilai pretrip project.json under {path}")


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _assert_no_runtime_or_raw_payload_fragments(payload: Any) -> None:
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True).lower()
    for fragment in (
        "/safety",
        "phase1incidentbridge",
        "scout_phase2_incident_bridge",
        "<trkpt",
        "\"coordinates\"",
        "catographydata",
        "pdrsample",
        ".gpx",
        ".grd",
        ".hdr",
        ".jpg",
        ".jpeg",
        ".tif",
        ".tiff",
        "incident_samples",
        "raw_samples",
    ):
        if fragment in serialized:
            raise ValueError(f"forbidden departure gate fragment: {fragment}")
