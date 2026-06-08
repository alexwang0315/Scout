from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from pretrip_eta_plan import PreTripEtaPlan
from pretrip_models import PreTripPackage, PreTripRetreatRouteCandidate


class RemoteSummarySourcePackage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    package_id: str
    project_id: str
    version: str
    status: str
    package_ref: str | None = None
    planned_eta_ref: str | None = None
    readiness_report_ref: str | None = None
    source_artifact_count: int = Field(ge=0)
    planning_reference_count: int = Field(ge=0)


class RemoteSummaryReadiness(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str
    finding_count: int = Field(ge=0)


class RemoteSummaryRoute(BaseModel):
    model_config = ConfigDict(extra="forbid")

    route_name: str
    planned_start: str
    day1_target_name: str
    day1_target_eta: str
    turn_back_checkpoint_name: str
    turn_back_checkpoint_eta: str
    return_to_entry_eta: str


class RemoteSummaryRetreatRoute(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str
    retreat_type: str
    expected_use: str
    review_state: str
    confidence: str
    reversed_from_primary_route: bool
    distance_m: float = Field(ge=0.0)
    summary: str


class PreTripRemoteContactSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    summary_id: str
    artifact_kind: Literal["remote_contact_predeparture_summary"] = (
        "remote_contact_predeparture_summary"
    )
    project_id: str
    audience: Literal["remote_contacts"] = "remote_contacts"
    route: RemoteSummaryRoute
    retreat_route_summary: RemoteSummaryRetreatRoute
    readiness: RemoteSummaryReadiness
    source_package: RemoteSummarySourcePackage
    conservative_notes: list[str] = Field(default_factory=list)


def load_json(path: Path | str) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def build_chilai_remote_contact_summary(project_root: Path | str) -> PreTripRemoteContactSummary:
    root = Path(project_root)
    project = load_json(root / "project.json")
    package = PreTripPackage.model_validate(load_json(root / project["reviewed_package_ref"]))
    eta_plan = PreTripEtaPlan.model_validate(load_json(root / project["planned_eta_ref"]))
    readiness_report = load_json(root / project["readiness_report_ref"])
    return build_remote_contact_summary(
        package,
        eta_plan,
        readiness_report,
        project_refs=project,
    )


def build_remote_contact_summary(
    package: PreTripPackage | dict[str, Any],
    eta_plan: PreTripEtaPlan | dict[str, Any],
    readiness_report: dict[str, Any],
    *,
    project_refs: dict[str, Any] | None = None,
) -> PreTripRemoteContactSummary:
    pretrip_package = (
        package if isinstance(package, PreTripPackage) else PreTripPackage.model_validate(package)
    )
    planned_eta = eta_plan if isinstance(eta_plan, PreTripEtaPlan) else PreTripEtaPlan.model_validate(eta_plan)
    refs = project_refs or {}
    assumption = planned_eta.assumption

    if assumption.planned_start_time is None:
        raise ValueError("planned ETA assumption must include planned_start_time")
    if assumption.target_eta is None:
        raise ValueError("planned ETA assumption must include target_eta")
    if assumption.turn_back_checkpoint_eta is None:
        raise ValueError("planned ETA assumption must include turn_back_checkpoint_eta")
    if assumption.return_to_entry_eta_if_turn_back_at_checkpoint is None:
        raise ValueError("planned ETA assumption must include return_to_entry_eta_if_turn_back_at_checkpoint")

    retreat_route = _selected_retreat_route(pretrip_package.retreat_route_candidates)
    readiness_status = str(readiness_report.get("status") or "unknown")
    findings = readiness_report.get("findings", [])
    finding_count = len(findings) if isinstance(findings, list) else 0

    return PreTripRemoteContactSummary(
        summary_id=f"remote_contact_summary.{pretrip_package.project_id}.v0",
        project_id=pretrip_package.project_id,
        route=RemoteSummaryRoute(
            route_name=pretrip_package.route_summary.route_name,
            planned_start=assumption.planned_start_time,
            day1_target_name=assumption.day1_target_node_name,
            day1_target_eta=assumption.target_eta,
            turn_back_checkpoint_name=assumption.turn_back_checkpoint_node_name,
            turn_back_checkpoint_eta=assumption.turn_back_checkpoint_eta,
            return_to_entry_eta=assumption.return_to_entry_eta_if_turn_back_at_checkpoint,
        ),
        retreat_route_summary=RemoteSummaryRetreatRoute(
            label=retreat_route.label,
            retreat_type=retreat_route.retreat_type,
            expected_use=retreat_route.expected_use,
            review_state=str(retreat_route.review_state),
            confidence=retreat_route.confidence,
            reversed_from_primary_route=retreat_route.reversed_from_primary_route,
            distance_m=round(retreat_route.distance_m, 2),
            summary=_retreat_summary(retreat_route),
        ),
        readiness=RemoteSummaryReadiness(status=readiness_status, finding_count=finding_count),
        source_package=RemoteSummarySourcePackage(
            package_id=pretrip_package.package_id,
            project_id=pretrip_package.project_id,
            version=pretrip_package.version,
            status=pretrip_package.status,
            package_ref=refs.get("reviewed_package_ref") or refs.get("package_ref"),
            planned_eta_ref=refs.get("planned_eta_ref"),
            readiness_report_ref=refs.get("readiness_report_ref"),
            source_artifact_count=len(pretrip_package.source_artifacts),
            planning_reference_count=len(pretrip_package.planning_references),
        ),
        conservative_notes=[
            "Shareable summary only; raw GPX, DTM, photo, and incident/sample payloads are intentionally excluded.",
            "ETA uses route-guide timing with total elapsed time including normal rest; sun-window validation is not included in this artifact.",
            "Remote contacts should treat the turn-back and return-to-entry times as check-in expectations, not as live safety status.",
        ],
    )


def _selected_retreat_route(
    retreat_routes: list[PreTripRetreatRouteCandidate],
) -> PreTripRetreatRouteCandidate:
    for candidate in retreat_routes:
        if candidate.retreat_type == "return_to_entry":
            return candidate
    if retreat_routes:
        return retreat_routes[0]
    raise ValueError("at least one retreat route candidate is required")


def _retreat_summary(retreat_route: PreTripRetreatRouteCandidate) -> str:
    route_kind = "reversed primary route" if retreat_route.reversed_from_primary_route else "planned retreat route"
    return (
        f"{retreat_route.label}; {route_kind}; "
        f"{round(retreat_route.distance_m / 1000.0, 2)} km; "
        f"expected use: {retreat_route.expected_use}."
    )
