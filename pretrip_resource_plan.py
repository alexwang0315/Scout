from __future__ import annotations

import json
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from pretrip_models import CandidateReviewState


class ResourcePlanStatus(StrEnum):
    CANDIDATE_ONLY = "candidate_only"


class PlanningInputStatus(StrEnum):
    HUMAN_PROVIDED_PLACEHOLDER = "human_provided_placeholder"
    HUMAN_REVIEWED = "human_reviewed"
    MODEL_CANDIDATE = "model_candidate"
    NEEDS_REVIEW = "needs_review"


class DeviceReadiness(StrEnum):
    READY = "ready"
    LIMITED = "limited"
    MISSING = "missing"
    UNKNOWN = "unknown"


class EquipmentReadiness(StrEnum):
    AVAILABLE = "available"
    LIMITED = "limited"
    MISSING = "missing"
    UNKNOWN = "unknown"


class StrictResourceModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ResourceReviewBoundary(StrictResourceModel):
    input_status: PlanningInputStatus = PlanningInputStatus.NEEDS_REVIEW
    review_state: CandidateReviewState = CandidateReviewState.NEEDS_REVIEW
    human_review_required: bool = True
    reviewed_by: str | None = None
    reviewed_at: str | None = None
    review_ref: str | None = None
    notes: str = ""

    @model_validator(mode="after")
    def require_review_ref_for_accepted_items(self) -> "ResourceReviewBoundary":
        if self.review_state == CandidateReviewState.ACCEPTED and not self.review_ref:
            raise ValueError("accepted resource-plan entries require review_ref")
        if self.input_status == PlanningInputStatus.MODEL_CANDIDATE and not self.human_review_required:
            raise ValueError("model candidates require human review")
        return self


class MissionOwnerPlan(StrictResourceModel):
    owner_id: str
    display_label: str
    role: Literal["mission_owner", "team_leader"] = "mission_owner"
    review: ResourceReviewBoundary


class TeamMemberPlan(StrictResourceModel):
    member_id: str
    display_label: str
    role: Literal["leader", "member", "support"] = "member"
    device_ids: list[str] = Field(default_factory=list)
    required_for_departure: bool = True
    review: ResourceReviewBoundary


class DevicePlan(StrictResourceModel):
    device_id: str
    owner_ref: str
    device_type: Literal[
        "phone",
        "watch",
        "satellite_messenger",
        "power_bank",
        "headlamp",
        "other",
    ]
    readiness: DeviceReadiness = DeviceReadiness.UNKNOWN
    capability_labels: list[str] = Field(default_factory=list)
    battery_required: bool = True
    estimated_start_battery_pct: int | None = Field(default=None, ge=0, le=100)
    notes: str = ""
    review: ResourceReviewBoundary


class EquipmentPlan(StrictResourceModel):
    equipment_id: str
    owner_ref: str | None = None
    category: Literal[
        "navigation",
        "communication",
        "shelter",
        "water",
        "food",
        "first_aid",
        "lighting",
        "weather_protection",
        "other",
    ]
    label: str
    readiness: EquipmentReadiness = EquipmentReadiness.UNKNOWN
    quantity_label: str | None = None
    required_for_departure: bool = True
    notes: str = ""
    review: ResourceReviewBoundary


class EmergencyPlanSummary(StrictResourceModel):
    plan_id: str
    emergency_contact_aliases: list[str] = Field(default_factory=list)
    emergency_access_notes: list[str] = Field(default_factory=list)
    nearest_known_help_ref: str | None = None
    secret_contact_details_included: Literal[False] = False
    review: ResourceReviewBoundary


class RemoteContactPlanSummary(StrictResourceModel):
    plan_id: str
    remote_contact_aliases: list[str] = Field(default_factory=list)
    shareable_summary_ref: str | None = None
    planned_checkin_labels: list[str] = Field(default_factory=list)
    escalation_policy_summary: str
    excluded_payloads: list[str] = Field(default_factory=list)
    secret_contact_details_included: Literal[False] = False
    review: ResourceReviewBoundary


class DepartureReadinessContext(StrictResourceModel):
    status: Literal["candidate_context_only"] = "candidate_context_only"
    hard_readiness_mutation_allowed: Literal[False] = False
    blocks_existing_eta_or_readiness: Literal[False] = False
    warning_candidates: list[str] = Field(default_factory=list)
    blocker_candidates: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class PreTripResourcePlan(StrictResourceModel):
    plan_id: str
    artifact_kind: Literal["resource_team_departure_plan"] = "resource_team_departure_plan"
    project_id: str
    status: ResourcePlanStatus = ResourcePlanStatus.CANDIDATE_ONLY
    package_ref: str | None = None
    readiness_report_ref: str | None = None
    remote_contact_summary_ref: str | None = None
    mission_owner: MissionOwnerPlan
    team_members: list[TeamMemberPlan] = Field(default_factory=list)
    devices: list[DevicePlan] = Field(default_factory=list)
    equipment: list[EquipmentPlan] = Field(default_factory=list)
    emergency_plan: EmergencyPlanSummary
    remote_contact_plan: RemoteContactPlanSummary
    departure_readiness_context: DepartureReadinessContext = Field(
        default_factory=DepartureReadinessContext
    )
    source_refs: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    external_api_calls_made: Literal[False] = False
    raw_payloads_embedded: Literal[False] = False
    pii_redaction_policy: str = "aliases_only_no_phone_email_or_secret_contact_details"

    @model_validator(mode="after")
    def enforce_fixture_first_boundary(self) -> "PreTripResourcePlan":
        if self.status != ResourcePlanStatus.CANDIDATE_ONLY:
            raise ValueError("resource plan must remain candidate_only")
        if self.external_api_calls_made:
            raise ValueError("resource plan builder must not make external API calls")
        if self.raw_payloads_embedded:
            raise ValueError("resource plan must not embed raw payloads")
        _assert_shareable_payload(self.model_dump(mode="json"))
        return self

    def to_json(self) -> str:
        return json.dumps(
            self.model_dump(mode="json"),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        ) + "\n"


def build_chilai_resource_plan(project_root: Path | str | None = None) -> PreTripResourcePlan:
    project_refs = _load_project_refs(project_root)
    accepted_review = ResourceReviewBoundary(
        input_status=PlanningInputStatus.HUMAN_REVIEWED,
        review_state=CandidateReviewState.ACCEPTED,
        human_review_required=False,
        reviewed_by="reviewer.planning_admin",
        reviewed_at="2026-05-02T20:00:00+08:00",
        review_ref="reviews/human_reviews.json#resource-plan-placeholder",
        notes="Fixture placeholder accepted for validation context; no contact secrets included.",
    )
    placeholder_review = ResourceReviewBoundary(
        input_status=PlanningInputStatus.HUMAN_PROVIDED_PLACEHOLDER,
        review_state=CandidateReviewState.NEEDS_REVIEW,
        human_review_required=True,
        notes="Planning placeholder requires confirmation before departure.",
    )

    return PreTripResourcePlan(
        plan_id="resource_plan.chilai_nanhua_day1.v0",
        project_id="chilai_nanhua_day1",
        package_ref=project_refs.get("reviewed_package_ref") or project_refs.get("package_ref"),
        readiness_report_ref=project_refs.get("readiness_report_ref"),
        remote_contact_summary_ref=project_refs.get("remote_contact_summary_ref"),
        mission_owner=MissionOwnerPlan(
            owner_id="person.owner_placeholder",
            display_label="Mission owner placeholder",
            review=accepted_review,
        ),
        team_members=[
            TeamMemberPlan(
                member_id="person.owner_placeholder",
                display_label="Mission owner placeholder",
                role="leader",
                device_ids=["device.owner_phone", "device.owner_watch"],
                review=accepted_review,
            ),
            TeamMemberPlan(
                member_id="person.teammate_placeholder",
                display_label="Team member placeholder",
                role="member",
                device_ids=["device.teammate_phone"],
                review=placeholder_review,
            ),
        ],
        devices=[
            DevicePlan(
                device_id="device.owner_phone",
                owner_ref="person.owner_placeholder",
                device_type="phone",
                readiness=DeviceReadiness.READY,
                capability_labels=["offline_map", "gps", "cellular_checkin"],
                estimated_start_battery_pct=95,
                review=accepted_review,
            ),
            DevicePlan(
                device_id="device.owner_watch",
                owner_ref="person.owner_placeholder",
                device_type="watch",
                readiness=DeviceReadiness.READY,
                capability_labels=["gps_track", "heart_rate", "battery_status"],
                estimated_start_battery_pct=90,
                review=accepted_review,
            ),
            DevicePlan(
                device_id="device.teammate_phone",
                owner_ref="person.teammate_placeholder",
                device_type="phone",
                readiness=DeviceReadiness.UNKNOWN,
                capability_labels=["backup_navigation", "cellular_checkin"],
                estimated_start_battery_pct=None,
                notes="Candidate placeholder until teammate confirms start battery.",
                review=placeholder_review,
            ),
            DevicePlan(
                device_id="device.shared_power_bank",
                owner_ref="person.owner_placeholder",
                device_type="power_bank",
                readiness=DeviceReadiness.READY,
                capability_labels=["device_charging"],
                estimated_start_battery_pct=100,
                review=accepted_review,
            ),
        ],
        equipment=[
            EquipmentPlan(
                equipment_id="equipment.offline_map_cache",
                owner_ref="person.owner_placeholder",
                category="navigation",
                label="Offline map cache",
                readiness=EquipmentReadiness.AVAILABLE,
                quantity_label="team shared",
                review=accepted_review,
            ),
            EquipmentPlan(
                equipment_id="equipment.headlamp_set",
                owner_ref=None,
                category="lighting",
                label="Headlamp set",
                readiness=EquipmentReadiness.AVAILABLE,
                quantity_label="one per hiker placeholder",
                review=placeholder_review,
            ),
            EquipmentPlan(
                equipment_id="equipment.water_plan",
                owner_ref=None,
                category="water",
                label="Water carry and refill plan",
                readiness=EquipmentReadiness.LIMITED,
                quantity_label="capacity placeholder",
                notes="Needs reviewer confirmation against weather/daylight context.",
                review=placeholder_review,
            ),
            EquipmentPlan(
                equipment_id="equipment.first_aid",
                owner_ref="person.owner_placeholder",
                category="first_aid",
                label="First aid kit",
                readiness=EquipmentReadiness.AVAILABLE,
                review=accepted_review,
            ),
        ],
        emergency_plan=EmergencyPlanSummary(
            plan_id="emergency_plan.chilai_nanhua_day1.v0",
            emergency_contact_aliases=["remote.primary_placeholder", "remote.backup_placeholder"],
            emergency_access_notes=[
                "Use reviewed route retreat summary before departure.",
                "Escalation details live outside this fixture and are not stored in repo.",
            ],
            nearest_known_help_ref="map.poi_candidate.help_placeholder",
            review=placeholder_review,
        ),
        remote_contact_plan=RemoteContactPlanSummary(
            plan_id="remote_contact_plan.chilai_nanhua_day1.v0",
            remote_contact_aliases=["remote.primary_placeholder", "remote.backup_placeholder"],
            shareable_summary_ref=project_refs.get("remote_contact_summary_ref"),
            planned_checkin_labels=[
                "pre-departure check-in",
                "turn-back checkpoint expectation",
                "day1 target arrival expectation",
            ],
            escalation_policy_summary=(
                "Remote contacts receive aliases, route timing expectations, and retreat summary only; "
                "phone numbers and private escalation channels stay outside repo fixtures."
            ),
            excluded_payloads=[
                "raw_gpx",
                "raw_dtm",
                "raw_photos",
                "pdr_samples",
                "phone_numbers",
                "email_addresses",
                "private_messaging_handles",
            ],
            review=placeholder_review,
        ),
        departure_readiness_context=DepartureReadinessContext(
            warning_candidates=[
                "teammate phone start battery needs confirmation",
                "water carry and refill plan needs reviewer confirmation",
                "headlamp set count is a planning placeholder",
            ],
            notes=[
                "Resource plan is candidate-only and does not alter outputs/readiness_report.json.",
                "Accepted placeholders are validation context, not proof of future field conditions.",
            ],
        ),
        source_refs=[
            project_refs.get("reviewed_package_ref") or "outputs/pretrip_package.reviewed.json",
            project_refs.get("readiness_report_ref") or "outputs/readiness_report.json",
            project_refs.get("remote_contact_summary_ref") or "outputs/remote_contact_summary.json",
        ],
        assumptions=[
            "Two-person team placeholder for fixture validation.",
            "Contact details are managed outside repo fixtures.",
            "Device and equipment readiness are pre-departure planning claims requiring review.",
        ],
    )


def load_resource_plan(path: Path | str) -> PreTripResourcePlan:
    return PreTripResourcePlan.model_validate_json(Path(path).read_text(encoding="utf-8"))


def _load_project_refs(project_root: Path | str | None) -> dict[str, Any]:
    if project_root is None:
        return {}
    project_path = Path(project_root) / "project.json"
    if not project_path.exists():
        return {}
    return json.loads(project_path.read_text(encoding="utf-8"))


def _assert_shareable_payload(payload: Any) -> None:
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
        "@",
        "+886",
    ]
    for fragment in forbidden_fragments:
        if fragment in serialized:
            raise ValueError(f"resource plan contains forbidden shareable fragment: {fragment}")
