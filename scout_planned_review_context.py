"""Immutable, version-bound human declarations and source-backed Planned reviews.

This store never edits a Planned bundle or promotes declarations to observations.
Supplementation creates a new revision; GETs verify hashes without writing. The
materializer emits isolated assessor inputs and explicit provenance, not runtime
permission, an accepted mission graph, or measured team capability.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
from typing import Any, Literal

from pydantic import Field, StrictBool, field_validator, model_validator

from scout_planned_route_artifacts import (
    AUTHORITY, SHA_PATTERN, VERSION_PATTERN, _atomic_json, _digest, _project,
    _read_json, _safe_path, _signed, _verify_signed, canonical_bytes,
    get_planned_version,
)
from scout_planned_route_models import PlannedModel, PlannedRouteConflict


SCHEMA_VERSION = "plannedReviewContext.v1"
STORE_REF = "reviews/planned_review_context"
REVISION_PATTERN = r"^context\.[a-f0-9]{24,64}$"
BINDING_KEYS = ("project_id", "version_id", "manifest_sha256", "geometry_sha256", "itinerary_sha256")
NAVIGATION_FIELDS = (
    "offline_map_downloaded", "gpx_loaded_on_device", "contour_skill_confirmed",
    "terrain_feature_skill_confirmed", "junction_points_known",
    "retreat_direction_understood", "backup_positioning_available",
    "terrain_risk_layers_understood",
)
POLICY_FIELDS = ("requires_daylight", "water_available", "retreat_available", "signal_expected")
BOUNDARY = {**AUTHORITY, "operational": False, "promotion_allowed": False,
            "human_review_required": True}


class AwareModel(PlannedModel):
    @field_validator("*", mode="after")
    @classmethod
    def explicit_timezone(cls, value):
        if isinstance(value, datetime) and value.utcoffset() is None:
            raise ValueError("Use an ISO date/time with an explicit timezone offset.")
        return value


class ReviewEvidenceRef(AwareModel):
    evidence_id: str = Field(min_length=1, max_length=120, pattern=r"^[A-Za-z0-9_.:-]+$")
    ref: str = Field(min_length=1, max_length=600)
    sha256: str = Field(pattern=SHA_PATTERN)
    source_kind: Literal["forecast", "daylight", "route_condition", "map", "narrative",
                         "team_calibration", "equipment_checklist", "human_review", "terrain"]
    description: str = Field(min_length=1, max_length=2000)
    issued_at: datetime | None = None
    valid_from: datetime | None = None
    valid_to: datetime | None = None

    @field_validator("ref")
    @classmethod
    def workspace_reference(cls, value):
        _validate_ref(value)
        return value

    @model_validator(mode="after")
    def valid_period(self):
        if self.valid_from and self.valid_to and self.valid_to < self.valid_from:
            raise ValueError("Evidence validity must end after it starts.")
        return self


class ReviewStatement(AwareModel):
    status: Literal["pending", "reviewed", "rejected"] = "pending"
    reviewer_alias: str | None = Field(default=None, min_length=1, max_length=120)
    reviewed_at: datetime | None = None
    conclusion: str | None = Field(default=None, min_length=1, max_length=4000)
    evidence_ids: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def traceable_review(self):
        if len(self.evidence_ids) != len(set(self.evidence_ids)):
            raise ValueError("Evidence IDs within a review must be unique.")
        if self.status != "pending" and not all((self.reviewer_alias, self.reviewed_at, self.conclusion, self.evidence_ids)):
            raise ValueError("A completed review requires reviewer, time, conclusion and source evidence IDs.")
        return self


class DeclaredMember(PlannedModel):
    member_id: str = Field(min_length=1, max_length=120)
    label: str | None = Field(default=None, max_length=120)
    experience: str | None = Field(default=None, max_length=2000)
    experience_level: Literal["beginner", "novice", "intermediate", "experienced", "expert"] | None = None
    planned_pace_kmh: float | None = Field(default=None, gt=0, le=20)
    reserve_minutes: float | None = Field(default=None, ge=0)
    rest_need_minutes: float | None = Field(default=None, ge=0)
    pack_weight_kg: float | None = Field(default=None, ge=0)
    first_time_similar_route: StrictBool | None = None
    offline_map_skill: StrictBool | None = None
    conditions: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)


class DeclaredEquipment(PlannedModel):
    item: str = Field(min_length=1, max_length=200)
    state: Literal["ready", "missing", "unknown"] = "unknown"
    member_id: str | None = Field(default=None, max_length=120)
    note: str | None = Field(default=None, max_length=2000)
    evidence_ids: list[str] = Field(default_factory=list)


class DeclaredNavigation(PlannedModel):
    offline_map_downloaded: StrictBool | None = None
    gpx_loaded_on_device: StrictBool | None = None
    contour_skill_confirmed: StrictBool | None = None
    terrain_feature_skill_confirmed: StrictBool | None = None
    junction_points_known: StrictBool | None = None
    retreat_direction_understood: StrictBool | None = None
    backup_positioning_available: StrictBool | None = None
    terrain_risk_layers_understood: StrictBool | None = None
    team_map_user_count: int | None = Field(default=None, ge=0, strict=True)


class DeclaredReadiness(PlannedModel):
    team_slowest_basis_confirmed: StrictBool | None = None
    departure_time_confirmed: StrictBool | None = None
    equipment_confirmed: StrictBool | None = None
    remote_contact_confirmed: StrictBool | None = None


class DeclaredTransport(AwareModel):
    mode: str | None = Field(default=None, max_length=200)
    meeting_point: str | None = Field(default=None, max_length=1000)
    outbound_at: datetime | None = None
    latest_return_at: datetime | None = None
    return_limit_point_index: int | None = Field(default=None, ge=0, strict=True)
    return_constraint: str | None = Field(default=None, max_length=2000)
    turnaround_point_index: int | None = Field(default=None, ge=0, strict=True)
    turnaround_at: datetime | None = None

    @model_validator(mode="after")
    def explicit_turnaround_pair(self):
        if (self.turnaround_point_index is None) != (self.turnaround_at is None):
            raise ValueError("A declared turnaround requires both an exact point occurrence and a timezone-aware deadline.")
        if self.turnaround_at and self.latest_return_at and self.turnaround_at > self.latest_return_at:
            raise ValueError("The turnaround deadline cannot be later than the latest return limit.")
        return self


class PlannedCheckpointReview(PlannedModel):
    point_index: int = Field(ge=0, strict=True)
    review: ReviewStatement = Field(default_factory=ReviewStatement)
    water_available: StrictBool | None = None
    retreat_available: StrictBool | None = None
    signal_expected: StrictBool | None = None
    requires_daylight: StrictBool | None = None
    stop_suitability: Literal["candidate", "avoid", "unknown"] = "unknown"
    camp_suitability: Literal["candidate", "avoid", "unknown"] = "unknown"
    campsite_legal_use: StrictBool | None = None
    campsite_capacity: int | None = Field(default=None, ge=1, strict=True)
    notes: str | None = Field(default=None, max_length=4000)


class PlannedSegmentPolicy(PlannedModel):
    from_point_index: int = Field(ge=0, strict=True)
    to_point_index: int = Field(ge=0, strict=True)
    requires_daylight: StrictBool | None = None
    water_available: StrictBool | None = None
    retreat_available: StrictBool | None = None
    signal_expected: StrictBool | None = None
    review: ReviewStatement = Field(default_factory=ReviewStatement)
    notes: str | None = Field(default=None, max_length=4000)

    @model_validator(mode="after")
    def ordered(self):
        if self.to_point_index <= self.from_point_index:
            raise ValueError("A segment review needs distinct ordered route point indices.")
        return self


class PlannedPermissionReview(PlannedModel):
    point_index: int = Field(ge=0, strict=True)
    remaining_safety_buffer_minutes: float | None = Field(default=None, ge=0)
    next_segment_uncertainty_minutes: float | None = Field(default=None, ge=0)
    weather_reserve_minutes: float | None = Field(default=None, ge=0)
    daylight_reserve_minutes: float | None = Field(default=None, ge=0)
    retreat_reserve_minutes: float | None = Field(default=None, ge=0)
    slowest_member_reserve_minutes: float | None = Field(default=None, ge=0)
    weather_window_impact: str | None = Field(default=None, max_length=2000)
    daylight_impact: str | None = Field(default=None, max_length=2000)
    retreat_impact: str | None = Field(default=None, max_length=2000)
    location_constraint: str | None = Field(default=None, max_length=2000)
    review: ReviewStatement = Field(default_factory=ReviewStatement)
    weather_review: ReviewStatement = Field(default_factory=ReviewStatement)
    daylight_review: ReviewStatement = Field(default_factory=ReviewStatement)
    retreat_review: ReviewStatement = Field(default_factory=ReviewStatement)


class PlannedNarrativeReview(PlannedModel):
    briefing_evidence_id: str | None = None
    review: ReviewStatement = Field(default_factory=ReviewStatement)
    notes: str | None = Field(default=None, max_length=4000)


class PlannedReviewDeclaration(AwareModel):
    declared_by: str = Field(min_length=1, max_length=120)
    declared_at: datetime
    team_size: int | None = Field(default=None, ge=1, strict=True)
    members: list[DeclaredMember] = Field(default_factory=list)
    equipment: list[DeclaredEquipment] = Field(default_factory=list)
    navigation: DeclaredNavigation = Field(default_factory=DeclaredNavigation)
    readiness: DeclaredReadiness = Field(default_factory=DeclaredReadiness)
    transport: DeclaredTransport = Field(default_factory=DeclaredTransport)
    goals: list[str] = Field(default_factory=list)
    route_condition_evidence_ids: list[str] = Field(default_factory=list)
    evidence: list[ReviewEvidenceRef] = Field(default_factory=list)
    checkpoint_reviews: list[PlannedCheckpointReview] = Field(default_factory=list)
    segment_policies: list[PlannedSegmentPolicy] = Field(default_factory=list)
    permission_reviews: list[PlannedPermissionReview] = Field(default_factory=list)
    narrative: PlannedNarrativeReview = Field(default_factory=PlannedNarrativeReview)

    @model_validator(mode="after")
    def references_and_unique_targets(self):
        member_ids = [m.member_id for m in self.members]
        if len(member_ids) != len(set(member_ids)):
            raise ValueError("Member IDs must be unique.")
        if self.team_size is not None and len(member_ids) > self.team_size:
            raise ValueError("Declared members exceed the team size.")
        count = self.navigation.team_map_user_count
        if self.team_size is not None and count is not None and count > self.team_size:
            raise ValueError("Map user count exceeds the team size.")
        for item in self.equipment:
            if item.member_id and item.member_id not in member_ids:
                raise ValueError("Equipment member_id must identify a declared member.")
        evidence = {e.evidence_id: e for e in self.evidence}
        if len(evidence) != len(self.evidence):
            raise ValueError("Evidence IDs must be unique.")
        refs = [e.ref for e in self.evidence]
        if len(refs) != len(set(refs)):
            raise ValueError("Declare each evidence file once.")
        for key in ("checkpoint_reviews", "permission_reviews"):
            targets = [r.point_index for r in getattr(self, key)]
            if len(targets) != len(set(targets)):
                raise ValueError(f"{key} must have unique route point targets.")
        targets = [(r.from_point_index, r.to_point_index) for r in self.segment_policies]
        if len(targets) != len(set(targets)):
            raise ValueError("Segment policy point pairs must be unique.")
        referenced = set(self.route_condition_evidence_ids)
        for member in self.members:
            referenced.update(member.evidence_ids)
        for item in self.equipment:
            referenced.update(item.evidence_ids)
        reviews = [r.review for r in self.checkpoint_reviews + self.segment_policies]
        for item in self.permission_reviews:
            reviews.extend((item.review, item.weather_review, item.daylight_review, item.retreat_review))
        reviews.append(self.narrative.review)
        for review in reviews:
            referenced.update(review.evidence_ids)
        for item in self.permission_reviews:
            for key, kinds in (("weather_review", {"forecast"}), ("daylight_review", {"daylight"}),
                               ("retreat_review", {"route_condition", "map", "terrain"})):
                review = getattr(item, key)
                if review.status == "reviewed" and not any(evidence[eid].source_kind in kinds
                        for eid in review.evidence_ids if eid in evidence):
                    raise ValueError(f"{key} requires a relevant bound source kind.")
        if self.narrative.briefing_evidence_id:
            referenced.add(self.narrative.briefing_evidence_id)
            if self.narrative.briefing_evidence_id not in self.narrative.review.evidence_ids:
                raise ValueError("The narrative review must cite its exact briefing evidence.")
            if evidence.get(self.narrative.briefing_evidence_id) and evidence[self.narrative.briefing_evidence_id].source_kind != "narrative":
                raise ValueError("Briefing evidence must have source_kind narrative.")
        if referenced - evidence.keys():
            raise ValueError("A declared evidence ID has no bound source reference.")
        return self


class PlannedReviewContextRequest(PlannedModel):
    version_id: str = Field(pattern=VERSION_PATTERN.pattern)
    expected_manifest_sha256: str = Field(pattern=SHA_PATTERN)
    expected_geometry_sha256: str = Field(pattern=SHA_PATTERN)
    expected_itinerary_sha256: str = Field(pattern=SHA_PATTERN)
    expected_parent_revision_id: str | None = Field(default=None, pattern=REVISION_PATTERN)
    idempotency_key: str = Field(min_length=1, max_length=200)
    declaration: PlannedReviewDeclaration
    explicit_confirmation: Literal[True]


def _validate_ref(ref: str) -> None:
    parts = PurePosixPath(ref).parts
    banned = {"secrets", "credentials", "private_keys", "id_rsa", "id_ed25519", "authorized_keys"}
    if (not ref or PurePosixPath(ref).is_absolute() or "\\" in ref or ".." in parts
            or any(p.startswith(".") or p.lower() in banned for p in parts)
            or PurePosixPath(ref).suffix.lower() in {".pem", ".key", ".p12", ".pfx", ".keystore"}):
        raise ValueError("Evidence must be a non-secret, non-hidden project-relative file.")


def _path(root: Path, ref: str) -> Path:
    try:
        _validate_ref(ref)
    except ValueError as exc:
        raise PlannedRouteConflict("invalid_planned_review_ref", str(exc)) from exc
    return _safe_path(root, ref)


def _bytes(root: Path, ref: str) -> bytes:
    path = _path(root, ref)
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(fd, "rb") as stream:
            return stream.read()
    except OSError as exc:
        raise PlannedRouteConflict("planned_review_evidence_missing", f"Review evidence is unavailable: {ref}") from exc


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _bundle(root: Path, version_id: str) -> dict:
    if not VERSION_PATTERN.fullmatch(version_id):
        raise PlannedRouteConflict("invalid_planned_version", "Invalid Planned version ID.")
    value = get_planned_version(root, version_id)
    if value["source_status"]["status"] != "current":
        raise PlannedRouteConflict("planned_review_sources_stale", "Planned source files changed; create a new plan before supplementing its review.")
    return value


def review_context_binding(bundle: dict) -> dict:
    return {key: bundle["manifest"][key] for key in BINDING_KEYS}


def _version_ref(version_id: str, filename: str) -> str:
    if not VERSION_PATTERN.fullmatch(version_id):
        raise PlannedRouteConflict("invalid_planned_version", "Invalid Planned version ID.")
    return f"{STORE_REF}/{version_id}/{filename}"


def _revision_ref(version_id: str, revision_id: str) -> str:
    if not re.fullmatch(REVISION_PATTERN, revision_id):
        raise PlannedRouteConflict("invalid_planned_review_revision", "Invalid review context revision ID.")
    return _version_ref(version_id, f"revisions/{revision_id}.json")


def _verify_record(root: Path, bundle: dict, record: dict, *, verify_sources: bool = True) -> dict:
    _verify_signed(record, "context_sha256")
    if record.get("schema_version") != SCHEMA_VERSION:
        raise PlannedRouteConflict("planned_review_schema_unsupported", "The saved review context uses an unsupported schema version.")
    if any(record.get(k) is not v for k, v in BOUNDARY.items()):
        raise PlannedRouteConflict("planned_review_authority_mismatch", "Review context must remain candidate-only.")
    if record.get("subject_binding") != review_context_binding(bundle):
        raise PlannedRouteConflict("planned_review_binding_stale", "Review context belongs to a different plan, geometry or timetable.")
    declaration = PlannedReviewDeclaration.model_validate(record.get("declaration"))
    if record.get("declaration") != declaration.model_dump(mode="json", exclude_unset=True):
        raise PlannedRouteConflict("planned_review_content_changed", "The saved declaration no longer matches its schema.")
    expected = {e.ref: e.sha256 for e in declaration.evidence}
    if record.get("source_hashes") != expected:
        raise PlannedRouteConflict("planned_review_content_changed", "Review evidence hashes differ from the declared sources.")
    if verify_sources:
        for ref, digest in expected.items():
            if _sha(_bytes(root, ref)) != digest:
                raise PlannedRouteConflict("planned_review_evidence_stale", f"Review source changed: {ref}")
    return record


def _validate_targets(bundle: dict, declaration: PlannedReviewDeclaration) -> None:
    raw_axis = bundle["preview"]["route_axis"]
    points = raw_axis.get("points", raw_axis.get("route_axis", [])) if isinstance(raw_axis, dict) else raw_axis
    count = len(points)
    indices = [r.point_index for r in declaration.checkpoint_reviews + declaration.permission_reviews]
    indices += [i for r in declaration.segment_policies for i in (r.from_point_index, r.to_point_index)]
    for point in (declaration.transport.return_limit_point_index, declaration.transport.turnaround_point_index):
        if point is not None:
            indices.append(point)
    if any(i >= count for i in indices):
        raise PlannedRouteConflict("planned_review_target_mismatch", "A review refers to a point outside the saved route axis.")
    for policy in declaration.segment_policies:
        if any(isinstance(p, dict) and p.get("break_before") for p in points[policy.from_point_index + 1:policy.to_point_index + 1]):
            raise PlannedRouteConflict("planned_review_crosses_gap", "A policy cannot assert continuity across a route geometry gap.")


def _current_pointer(root: Path, version_id: str) -> dict | None:
    ref = _version_ref(version_id, "current.json")
    if not _path(root, ref).exists():
        return None
    pointer = _read_json(root, ref)
    _verify_signed(pointer, "pointer_sha256")
    if pointer.get("project_id") != root.name or pointer.get("version_id") != version_id:
        raise PlannedRouteConflict("planned_review_pointer_mismatch", "Review selection belongs to another project or version.")
    _revision_ref(version_id, pointer.get("revision_id", ""))
    return pointer


def get_planned_review_context(project_root: Path, version_id: str, revision_id: str | None = None,
                               *, expected_context_sha256: str | None = None) -> dict | None:
    """Read a verified revision, or the current one; never repair or write on GET."""
    root, _ = _project(project_root)
    bundle = _bundle(root, version_id)
    pointer = _current_pointer(root, version_id)
    if revision_id is None:
        if pointer is None:
            return None
        revision_id = pointer["revision_id"]
    ref = _revision_ref(version_id, revision_id)
    record = _verify_record(root, bundle, _read_json(root, ref))
    if record.get("revision_id") != revision_id or record.get("context_ref") != ref:
        raise PlannedRouteConflict("planned_review_revision_mismatch", "Review revision identity does not match its file.")
    if pointer and pointer["revision_id"] == revision_id and pointer.get("context_sha256") != record["context_sha256"]:
        raise PlannedRouteConflict("planned_review_pointer_mismatch", "Current review pointer does not match its revision.")
    if expected_context_sha256 is not None and expected_context_sha256 != record["context_sha256"]:
        raise PlannedRouteConflict("planned_review_context_changed", "Review context changed; reload before analysing.")
    return {**record, "context_file_sha256": _sha(_bytes(root, ref)),
            "is_current": bool(pointer and pointer["revision_id"] == revision_id), "writes_performed": False}


def current_planned_review_context(project_root: Path, version_id: str) -> dict | None:
    return get_planned_review_context(project_root, version_id)


@contextmanager
def _writer(root: Path):
    path = _safe_path(root, f"{STORE_REF}/.write.lock")
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def _write_immutable(root: Path, ref: str, value: dict) -> None:
    path = _path(root, ref)
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = canonical_bytes(value)
    if path.exists():
        if _bytes(root, ref) != raw:
            raise PlannedRouteConflict("planned_review_revision_collision", "A different immutable review revision already occupies this ID.")
        return
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())


def save_planned_review_context(project_root: Path, request: PlannedReviewContextRequest | dict) -> dict:
    """Save a full replacement declaration with optimistic parent and safe retry.

    Supplementation is an explicit new complete declaration. Missing fields stay
    unknown instead of implicitly inheriting an older plan's declarations.
    """
    request = PlannedReviewContextRequest.model_validate(request)
    root, project_id = _project(project_root)
    command_sha, key_sha = _digest(request.model_dump(mode="json")), _digest(request.idempotency_key)
    receipt_ref = f"{STORE_REF}/idempotency/{key_sha}.json"
    with _writer(root):
        bundle = _bundle(root, request.version_id)
        binding = review_context_binding(bundle)
        for field in ("manifest_sha256", "geometry_sha256", "itinerary_sha256"):
            if getattr(request, f"expected_{field}") != binding[field]:
                raise PlannedRouteConflict("planned_review_binding_stale", f"The expected {field} no longer matches this plan.")
        _validate_targets(bundle, request.declaration)
        for evidence in request.declaration.evidence:
            if _sha(_bytes(root, evidence.ref)) != evidence.sha256:
                raise PlannedRouteConflict("planned_review_evidence_stale", f"Review source changed: {evidence.ref}")
        pointer = _current_pointer(root, request.version_id)
        current_id = pointer["revision_id"] if pointer else None
        prior_record = None
        if _path(root, receipt_ref).exists():
            receipt = _read_json(root, receipt_ref)
            _verify_signed(receipt, "receipt_sha256")
            if receipt.get("command_sha256") != command_sha or receipt.get("project_id") != project_id:
                raise PlannedRouteConflict("planned_review_idempotency_conflict", "This key already identifies different review data.")
            prior_record = _verify_record(root, bundle, _read_json(root, receipt["context_ref"]))
            if current_id == prior_record["revision_id"]:
                return {**get_planned_review_context(root, request.version_id), "replayed": True, "writes_performed": False}
            if current_id != prior_record["parent_revision_id"]:
                # A late retry returns its old immutable receipt, never rolls the current pointer back.
                return {**get_planned_review_context(root, request.version_id, prior_record["revision_id"]),
                        "replayed": True, "superseded": True, "writes_performed": False}
        if request.expected_parent_revision_id != current_id:
            raise PlannedRouteConflict("planned_review_parent_changed", "A newer supplement exists; reload before saving.")
        revision_id = "context." + command_sha[:24]
        context_ref = _revision_ref(request.version_id, revision_id)
        if prior_record is None and _path(root, context_ref).exists():
            # Recover a crash after immutable revision publication but before its idempotency receipt.
            prior_record = _verify_record(root, bundle, _read_json(root, context_ref))
            if prior_record.get("command_sha256") != command_sha:
                raise PlannedRouteConflict("planned_review_revision_collision", "Immutable revision command does not match the retry.")
        record = prior_record or _signed({
            "schema_version": SCHEMA_VERSION, "project_id": project_id, "version_id": request.version_id,
            "revision_id": revision_id, "parent_revision_id": current_id, "context_ref": context_ref,
            "subject_binding": binding, "declaration": request.declaration.model_dump(mode="json"),
            "source_hashes": {e.ref: e.sha256 for e in request.declaration.evidence},
            "declaration_role": "human_declared_planning_inputs",
            "review_role": "source_backed_human_review_not_observation",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "idempotency_key_sha256": key_sha, "command_sha256": command_sha, **BOUNDARY,
        }, "context_sha256")
        _write_immutable(root, context_ref, record)
        receipt = _signed({"project_id": project_id, "command_sha256": command_sha,
                           "context_ref": context_ref, "context_sha256": record["context_sha256"]}, "receipt_sha256")
        _write_immutable(root, receipt_ref, receipt)
        # Recheck live sources just before publishing current; a half-published revision is not selected.
        _verify_record(root, _bundle(root, request.version_id), record)
        pointer = _signed({"project_id": project_id, "version_id": request.version_id,
                           "revision_id": revision_id, "context_sha256": record["context_sha256"]}, "pointer_sha256")
        _atomic_json(root, _version_ref(request.version_id, "current.json"), pointer)
        return {**get_planned_review_context(root, request.version_id), "replayed": prior_record is not None, "writes_performed": True}


def _missing(code: str, reason: str, **target) -> dict:
    return {"code": code, "reason": reason, **target}


def planned_narrative_binding_status(project_root: Path, bundle: dict,
                                     evidence: ReviewEvidenceRef | dict | None) -> dict:
    """Separate a current Planned briefing artifact from historical narrative input.

    Plain text and an older briefing remain source material. Only a hash-verified
    JSON briefing carrying the exact version, geometry and timetable plus closed
    candidate boundaries can satisfy current-briefing review.
    """
    if evidence is None:
        return {"binding_valid": False, "binding_status": "not_provided"}
    evidence = ReviewEvidenceRef.model_validate(evidence)
    raw = _bytes(Path(project_root).resolve(), evidence.ref)
    if _sha(raw) != evidence.sha256:
        raise PlannedRouteConflict("planned_review_evidence_stale", "Narrative evidence changed after review.")
    try:
        payload = json.loads(raw)
    except (ValueError, UnicodeError):
        return {"binding_valid": False, "binding_status": "historical_or_unbound_text"}
    if not isinstance(payload, dict):
        return {"binding_valid": False, "binding_status": "historical_or_unbound_json"}
    bindings = [payload[key] for key in ("subject_binding", "input_binding", "planned_analysis_binding")
                if isinstance(payload.get(key), dict)]
    if not bindings:
        return {"binding_valid": False, "binding_status": "historical_or_unbound_json"}
    expected = review_context_binding(bundle)
    if any(any(value.get(key) != match for key, match in expected.items()) for value in bindings):
        return {"binding_valid": False, "binding_status": "different_or_incomplete_planned_binding"}
    if payload.get("candidate_only") is not True or payload.get("runtime_safety_truth") is not False:
        return {"binding_valid": False, "binding_status": "candidate_boundary_unproven"}
    if payload.get("departure_approval_granted") is True or payload.get("operational") is True:
        return {"binding_valid": False, "binding_status": "invalid_operational_claim"}
    return {"binding_valid": True, "binding_status": "same_planned_version", "subject_binding": expected}


def materialize_planned_review_inputs(owner_root: Path, bundle: dict, analysis_root: Path, graph: dict,
                                     context: dict | None = None) -> dict:
    """Copy verified review inputs into an isolated attempt and expose exact joins.

    The caller merges project_refs only after copying legacy source inputs, passes
    assessor_kwargs, and preserves source_report in each producer artifact. Unknown
    or pending/rejected policies never become False/True through default values.
    """
    owner_root, _ = _project(owner_root)
    analysis_root = Path(analysis_root).resolve()
    if analysis_root == owner_root or owner_root.is_relative_to(analysis_root):
        raise PlannedRouteConflict("invalid_planned_review_workspace", "Review materialization requires an isolated analysis workspace.")
    graph_binding = graph.get("input_binding") or {}
    expected_binding = review_context_binding(bundle)
    if any(graph_binding.get(key) != value for key, value in expected_binding.items()):
        raise PlannedRouteConflict("planned_review_graph_mismatch", "The supplied CP graph is not bound to this Planned version.")
    current = current_planned_review_context(owner_root, bundle["manifest"]["version_id"])
    if context is None:
        context = current
    elif not current or context.get("context_sha256") != current["context_sha256"]:
        raise PlannedRouteConflict("planned_review_context_changed", "The supplied review context is no longer current.")
    if context is None:
        return {"status": "missing", "subject_binding": expected_binding, "project_refs": {}, "assessor_kwargs": {
            "navigation": {}, "pace_fit": {}, "permission": []}, "segment_policy_updates": [],
            "checkpoint_reviews": [], "narrative": None, "context_revision_id": None,
            "context_sha256": None, "pretrip_input_bundle": None, "source_report": [], "input_hashes": {},
            "missing_inputs": [_missing("planned_review_context", "No same-version team, readiness and source-backed review supplement has been saved.")], **BOUNDARY}
    # Always use the verified disk record, never caller-supplied declaration data.
    context = current
    if context["subject_binding"] != expected_binding:
        raise PlannedRouteConflict("planned_review_binding_stale", "Review context does not match the supplied Planned bundle.")
    declaration = PlannedReviewDeclaration.model_validate(context["declaration"])
    nodes, edges = graph.get("nodes", []), graph.get("edges", [])
    node_by_point = {node["point_index"]: node for node in nodes}
    edge_by_pair = {(edge["start_point_index"], edge["end_point_index"]): edge for edge in edges}
    missing, policies, permission = [], [], []
    for policy in declaration.segment_policies:
        pair = (policy.from_point_index, policy.to_point_index)
        if pair not in edge_by_pair:
            raise PlannedRouteConflict("planned_review_target_mismatch", "A segment review has no exact edge on this version's CP graph.")
        if policy.review.status != "reviewed":
            missing.append(_missing("planned_segment_policy_review", "This segment policy remains pending or rejected.", segment_id=edge_by_pair[pair]["candidate_id"]))
            continue
        requirement = {key: getattr(policy, key) for key in POLICY_FIELDS if getattr(policy, key) is not None}
        policies.append({"segment_id": edge_by_pair[pair]["candidate_id"], "segment_candidate_id": edge_by_pair[pair]["candidate_id"],
                         "from_point_index": pair[0], "to_point_index": pair[1], "requirement": requirement,
                         "unknown_requirements": [key for key in POLICY_FIELDS if key not in requirement],
                         "review": policy.review.model_dump(mode="json"), "evidence_role": "source_backed_human_review", **BOUNDARY})
    for review in declaration.permission_reviews:
        if review.point_index not in node_by_point:
            raise PlannedRouteConflict("planned_review_target_mismatch", "A Permission review has no exact CP occurrence on this version's graph.")
        allowed = review.model_dump(mode="json", exclude_none=True)
        for key in ("point_index", "review", "weather_review", "daylight_review", "retreat_review"):
            allowed.pop(key, None)
        if review.review.status != "reviewed":
            allowed = {}
            missing.append(_missing("planned_permission_buffer_review", "Safety buffer is not reviewed; it will not be inferred from travel time.", point_index=review.point_index))
        for prefix, review_field in (("weather", "weather_review"), ("daylight", "daylight_review"), ("retreat", "retreat_review")):
            if getattr(review, review_field).status != "reviewed":
                allowed.pop(f"{prefix}_reserve_minutes", None)
                allowed.pop("weather_window_impact" if prefix == "weather" else f"{prefix}_impact", None)
                missing.append(_missing(f"planned_permission_{prefix}_review", f"The {prefix} review remains pending or rejected.", point_index=review.point_index))
        permission.append({"point_index": review.point_index, "checkpoint_id": node_by_point[review.point_index]["candidate_id"],
                           "kwargs": allowed, "review": review.model_dump(mode="json"), "evidence_role": "source_backed_human_review", **BOUNDARY})
    for point in (declaration.transport.return_limit_point_index, declaration.transport.turnaround_point_index):
        if point is not None and point not in node_by_point:
            raise PlannedRouteConflict("planned_review_target_mismatch", "A transport limit has no exact CP occurrence on this version's graph.")
    for review in declaration.checkpoint_reviews:
        if review.point_index not in node_by_point:
            raise PlannedRouteConflict("planned_review_target_mismatch", "A checkpoint review has no exact CP occurrence on this version's graph.")
    if declaration.team_size is None:
        missing.append(_missing("planned_team_size", "Team size has not been declared."))
    elif len(declaration.members) != declaration.team_size:
        missing.append(_missing("planned_team_members_incomplete", "Some declared team members have no individual profile."))
    for member in declaration.members:
        for key in ("experience", "planned_pace_kmh"):
            if getattr(member, key) is None and not (key == "experience" and member.experience_level):
                missing.append(_missing(f"planned_member_{key}", "Member experience or planned pace is missing.", member_id=member.member_id))
    if not declaration.equipment:
        missing.append(_missing("planned_equipment", "Equipment condition has not been declared."))
    for equipment in declaration.equipment:
        if equipment.state != "ready":
            missing.append(_missing("planned_equipment_unready", "Declared equipment remains missing or unknown.", item=equipment.item))
    for key in NAVIGATION_FIELDS:
        if getattr(declaration.navigation, key) is None:
            missing.append(_missing(f"planned_navigation_{key}", "This readiness confirmation remains unknown."))
    if not declaration.transport.mode:
        missing.append(_missing("planned_transport", "Transport mode has not been declared."))
    if declaration.transport.latest_return_at is None:
        missing.append(_missing("planned_latest_return", "The latest return limit has not been declared."))
    if not declaration.goals:
        missing.append(_missing("planned_user_goals", "The trip goals have not been declared."))
    if not declaration.route_condition_evidence_ids:
        missing.append(_missing("planned_route_condition_evidence", "Recent route condition evidence has not been provided."))
    reviewed_pairs = {(r["from_point_index"], r["to_point_index"]): r for r in policies}
    for pair, edge in edge_by_pair.items():
        reviewed = reviewed_pairs.get(pair)
        if not reviewed or reviewed["unknown_requirements"]:
            missing.append(_missing("planned_segment_policy_evidence", "This CP edge lacks complete reviewed daylight, water, retreat and communication policy.", segment_id=edge["candidate_id"]))
    narrative_evidence = next((e for e in declaration.evidence if e.evidence_id == declaration.narrative.briefing_evidence_id), None)
    narrative_binding = planned_narrative_binding_status(owner_root, bundle, narrative_evidence)
    if declaration.narrative.review.status != "reviewed" or not narrative_binding["binding_valid"]:
        missing.append(_missing("planned_narrative_review", "A same-version briefing has not been reviewed; historical narrative remains input evidence only."))
    prefix = "inputs/planned_review_context"
    hashes, source_report, evidence_targets = {}, [], {}
    snapshot_ref = f"{prefix}/context.json"
    snapshot = {k: v for k, v in context.items() if k not in ("context_file_sha256", "is_current", "writes_performed")}
    _write_immutable(analysis_root, snapshot_ref, snapshot)
    hashes[snapshot_ref] = _sha(_bytes(analysis_root, snapshot_ref))
    source_report.append({"scope": "owner", "ref": context["context_ref"], "sha256": context["context_file_sha256"],
                          "input_ref": snapshot_ref, "role": "human_declared_review_context"})
    current_ref = _version_ref(bundle["manifest"]["version_id"], "current.json")
    source_report.append({"scope": "owner", "ref": current_ref, "sha256": _sha(_bytes(owner_root, current_ref)),
                          "role": "review_context_current_selection"})
    for evidence in declaration.evidence:
        raw = _bytes(owner_root, evidence.ref)
        if _sha(raw) != evidence.sha256:
            raise PlannedRouteConflict("planned_review_evidence_stale", f"Review source changed while materializing: {evidence.ref}")
        suffix = Path(evidence.ref).suffix
        target_ref = f"{prefix}/evidence/{_digest(evidence.evidence_id)[:24]}{suffix}"
        target = _path(analysis_root, target_ref)
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists() and _bytes(analysis_root, target_ref) != raw:
            raise PlannedRouteConflict("planned_review_materialization_collision", "Existing attempt evidence differs from the saved review source.")
        if not target.exists():
            fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
            with os.fdopen(fd, "wb") as stream:
                stream.write(raw)
        hashes[target_ref], evidence_targets[evidence.evidence_id] = evidence.sha256, target_ref
        source_report.append({"scope": "owner", "ref": evidence.ref, "sha256": evidence.sha256,
                              "input_ref": target_ref, "evidence_id": evidence.evidence_id,
                              "role": "review_source_evidence", "source_kind": evidence.source_kind})
    members = []
    for member in declaration.members:
        value = member.model_dump(mode="json", exclude_none=True)
        if member.planned_pace_kmh is not None:
            value["planned_pace_mps"] = member.planned_pace_kmh / 3.6
        value.update(input_role="declared_user_input", capability_observed=False, **BOUNDARY)
        members.append(value)
    derived_binding = {**expected_binding, "review_context_revision_id": context["revision_id"],
                       "review_context_sha256": context["context_sha256"]}
    common = {"input_binding": derived_binding, "input_role": "declared_user_input", "declared_by": declaration.declared_by,
              "declared_at": declaration.declared_at.isoformat(), "observed": False, **BOUNDARY}
    payloads = {
        "team_status_ref": (f"{prefix}/team_status.json", {"team_size": declaration.team_size, "members": members, **common}),
        "resource_plan_ref": (f"{prefix}/resource_plan.json", {"team_members": members,
            "equipment": [e.model_dump(mode="json") for e in declaration.equipment],
            "navigation": declaration.navigation.model_dump(mode="json"),
            "readiness": declaration.readiness.model_dump(mode="json"),
            "transport": declaration.transport.model_dump(mode="json"), "goals": declaration.goals, **common}),
        "planned_review_context_ref": (snapshot_ref, snapshot),
        "planned_review_policy_ref": (f"{prefix}/segment_policies.json", {"policies": policies, **common}),
        "planned_permission_review_ref": (f"{prefix}/permission_reviews.json", {"reviews": permission, **common}),
        "planned_pretrip_input_bundle_ref": (f"{prefix}/pretrip_input_bundle.json", {
            "route": {"route_role": "planned", "geometry_sha256": expected_binding["geometry_sha256"]},
            "itinerary": bundle["preview"].get("itinerary", {}), "team_size": declaration.team_size,
            "members": members, "equipment": [e.model_dump(mode="json") for e in declaration.equipment],
            "navigation": declaration.navigation.model_dump(mode="json"),
            "readiness": declaration.readiness.model_dump(mode="json"),
            "transport": declaration.transport.model_dump(mode="json"), "goals": declaration.goals,
            "route_condition_evidence_ids": declaration.route_condition_evidence_ids,
            "source_evidence": [{**e.model_dump(mode="json"), "input_ref": evidence_targets[e.evidence_id]} for e in declaration.evidence],
            "checkpoint_reviews": [r.model_dump(mode="json") for r in declaration.checkpoint_reviews],
            "segment_policy_reviews": policies, "permission_reviews": permission,
            "narrative_review": declaration.narrative.model_dump(mode="json"), "missing_inputs": missing, **common}),
    }
    project_refs = {}
    for key, (ref, payload) in payloads.items():
        _write_immutable(analysis_root, ref, payload)
        hashes[ref] = _sha(_bytes(analysis_root, ref))
        project_refs[key] = ref
    narrative = {**declaration.narrative.model_dump(mode="json"),
                 "briefing_ref": evidence_targets.get(declaration.narrative.briefing_evidence_id),
                 "briefing_sha256": next((e.sha256 for e in declaration.evidence if e.evidence_id == declaration.narrative.briefing_evidence_id), None),
                 "evidence_role": "source_backed_human_review", **narrative_binding, **BOUNDARY}
    # Detect a concurrently selected newer supplement before returning usable inputs.
    latest = current_planned_review_context(owner_root, bundle["manifest"]["version_id"])
    if not latest or latest["context_sha256"] != context["context_sha256"]:
        raise PlannedRouteConflict("planned_review_context_changed", "Review data changed while building the analysis input snapshot.")
    return {"status": "partial" if missing else "ready", "context_revision_id": context["revision_id"],
            "context_sha256": context["context_sha256"], "context_file_ref": context["context_ref"],
            "context_file_sha256": context["context_file_sha256"], "subject_binding": derived_binding,
            "project_refs": project_refs, "assessor_kwargs": {"navigation": declaration.navigation.model_dump(exclude_none=True),
                "pace_fit": {"team_members": members}, "permission": permission},
            "segment_policy_updates": policies, "checkpoint_reviews": [r.model_dump(mode="json") for r in declaration.checkpoint_reviews],
            "narrative": narrative, "transport": declaration.transport.model_dump(mode="json"),
            "readiness": declaration.readiness.model_dump(mode="json"), "goals": declaration.goals,
            "evidence_targets": evidence_targets, "pretrip_input_bundle": payloads["planned_pretrip_input_bundle_ref"][1],
            "source_report": source_report, "input_hashes": hashes,
            "missing_inputs": missing, **BOUNDARY}
