from __future__ import annotations

from math import exp, sqrt
import json
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from scout_energy_baseline import internal_load_score
from scout_energy_models import (
    Confidence,
    ScoutEnergyBoundary,
    ScoutEnergyDataQuality,
    ScoutEnergyPrivacy,
    WearableActivitySummary,
    aggregate_sha256,
)


class CompanionCapabilityVector(BaseModel):
    model_config = ConfigDict(extra="forbid")

    route_effort_adjusted_moving_pace: float
    ascent_endurance_index: float
    descent_conservatism_index: float
    rest_frequency_per_hour: float
    median_rest_duration_min: float
    late_activity_fatigue_decay: float
    heart_rate_load_per_effort_unit: float


class CompanionMatchVisibilityPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    minimum_activity_count: int = Field(default=3, ge=1)
    activity_count: int = Field(ge=0)
    public_match_display_allowed: bool
    review_only: bool
    reasons: list[str] = Field(default_factory=list)


class CompanionCapabilityCapsule(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_kind: str = "scout_companion_capability_capsule"
    artifact_version: str = "companion_capability_capsule.v1"
    owner_profile_ref: str = "local_user.private"
    source_provider: str
    source_path: str
    sha256: str
    source_scope: str = "coarse_wearable_activity_summary"
    raw_track_shared: bool = False
    raw_health_payload_shared: bool = False
    exact_timestamps_shared: bool = False
    activity_count: int = Field(default=0, ge=0)
    capability_vector: CompanionCapabilityVector
    match_visibility: CompanionMatchVisibilityPolicy = Field(
        default_factory=lambda: CompanionMatchVisibilityPolicy(
            activity_count=0,
            public_match_display_allowed=False,
            review_only=True,
            reasons=["legacy capsule missing activity-count evidence; review only"],
        )
    )
    confidence: Confidence
    data_quality: ScoutEnergyDataQuality
    privacy: ScoutEnergyPrivacy = Field(default_factory=ScoutEnergyPrivacy)
    boundary: ScoutEnergyBoundary = Field(default_factory=ScoutEnergyBoundary)
    limitations: list[str]


class CompanionMatchResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_kind: str = "scout_companion_match_result"
    artifact_version: str = "companion_match.v1"
    source_provider: str
    source_path: str
    sha256: str
    query_profile_ref: str
    candidate_profile_ref: str
    match_score: int = Field(ge=0, le=100)
    match_band: Literal["similar_rhythm", "some_mismatch", "different_rhythm"]
    explanations: list[str]
    mismatch_notes: list[str]
    data_quality: ScoutEnergyDataQuality
    privacy: ScoutEnergyPrivacy = Field(default_factory=ScoutEnergyPrivacy)
    boundary: ScoutEnergyBoundary = Field(default_factory=ScoutEnergyBoundary)


class CompanionMatchReviewArtifact(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_kind: str = "scout_companion_match_review"
    artifact_version: str = "companion_match_review.v1"
    source_provider: str = "companion_capability_capsule_review"
    source_path: str
    sha256: str
    query_profile_ref: str
    candidate_count: int = Field(ge=0)
    ranked_matches: list[CompanionMatchResult]
    recommended_review_refs: list[str]
    review_policy: dict[str, Any]
    data_quality: ScoutEnergyDataQuality
    privacy: ScoutEnergyPrivacy = Field(default_factory=ScoutEnergyPrivacy)
    boundary: ScoutEnergyBoundary = Field(default_factory=ScoutEnergyBoundary)
    limitations: list[str]


class CompanionPoolConsentPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    explicit_consent: bool
    consent_scope: Literal["local_companion_pool"] = "local_companion_pool"
    allow_public_match_display: bool
    route_family_names_shared: bool = False
    raw_track_shared: bool = False
    raw_health_payload_shared: bool = False
    exact_timestamps_shared: bool = False
    remote_upload_allowed: bool = False
    withdrawal_supported: bool = True
    consent_version: str = "companion_pool_consent.v1"


class CompanionPoolEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_kind: str = "scout_companion_pool_entry"
    artifact_version: str = "companion_pool_entry.v1"
    source_provider: str = "companion_capability_capsule"
    source_path: str
    sha256: str
    owner_profile_ref: str
    public_profile_ref: str
    capsule: CompanionCapabilityCapsule
    consent: CompanionPoolConsentPolicy
    match_visibility: CompanionMatchVisibilityPolicy
    data_quality: ScoutEnergyDataQuality
    privacy: ScoutEnergyPrivacy = Field(default_factory=ScoutEnergyPrivacy)
    boundary: ScoutEnergyBoundary = Field(default_factory=ScoutEnergyBoundary)
    limitations: list[str]


class CompanionConsentPoolArtifact(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_kind: str = "scout_companion_consent_pool"
    artifact_version: str = "companion_consent_pool.v1"
    source_provider: str = "local_companion_consent_pool"
    source_path: str
    sha256: str
    pool_scope: Literal["local_only"] = "local_only"
    entry_count: int = Field(ge=0)
    entries: list[CompanionPoolEntry]
    data_quality: ScoutEnergyDataQuality
    privacy: ScoutEnergyPrivacy = Field(default_factory=ScoutEnergyPrivacy)
    boundary: ScoutEnergyBoundary = Field(default_factory=ScoutEnergyBoundary)
    limitations: list[str]


class CompanionPoolExchangePackage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_kind: str = "scout_companion_pool_exchange_package"
    artifact_version: str = "companion_pool_exchange_package.v1"
    source_provider: str = "local_companion_pool_exchange"
    source_path: str
    sha256: str
    package_scope: Literal["manual_local_exchange"] = "manual_local_exchange"
    remote_upload_allowed: bool = False
    entry_count: int = Field(ge=0)
    entries: list[CompanionPoolEntry]
    data_quality: ScoutEnergyDataQuality
    privacy: ScoutEnergyPrivacy = Field(default_factory=ScoutEnergyPrivacy)
    boundary: ScoutEnergyBoundary = Field(default_factory=ScoutEnergyBoundary)
    limitations: list[str]


class CompanionCommunityPublishEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_kind: str = "scout_companion_community_publish_entry"
    artifact_version: str = "companion_community_publish_entry.v1"
    public_profile_ref: str
    sha256: str
    source_pool_entry_sha256: str
    source_provider: str
    source_scope: str
    activity_count: int = Field(ge=0)
    capability_vector: CompanionCapabilityVector
    match_visibility: CompanionMatchVisibilityPolicy
    confidence: Confidence
    data_quality: ScoutEnergyDataQuality
    privacy: ScoutEnergyPrivacy = Field(default_factory=ScoutEnergyPrivacy)
    boundary: ScoutEnergyBoundary = Field(default_factory=ScoutEnergyBoundary)
    limitations: list[str]


class CompanionCommunityPublishDryRun(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_kind: str = "scout_companion_community_publish_dry_run"
    artifact_version: str = "companion_community_publish_dry_run.v1"
    source_provider: str = "local_companion_community_publish_dry_run"
    source_path: str
    sha256: str
    community_ref: str
    publish_mode: Literal["dry_run_only"] = "dry_run_only"
    explicit_community_consent: bool
    remote_upload_allowed: bool = False
    remote_upload_performed: bool = False
    network_request_performed: bool = False
    entry_count: int = Field(ge=0)
    entries: list[CompanionCommunityPublishEntry]
    data_quality: ScoutEnergyDataQuality
    privacy: ScoutEnergyPrivacy = Field(default_factory=ScoutEnergyPrivacy)
    boundary: ScoutEnergyBoundary = Field(default_factory=ScoutEnergyBoundary)
    limitations: list[str]


def build_companion_capability_capsule(
    activities: list[WearableActivitySummary],
    *,
    owner_profile_ref: str = "local_user.private",
) -> CompanionCapabilityCapsule:
    if not activities:
        raise ValueError("at least one wearable activity summary is required")
    vector = _capability_vector(activities)
    data_quality = _capsule_data_quality(activities)
    confidence = "medium" if len(activities) >= 3 and data_quality.heart_rate_confidence != "low" else "low"
    return CompanionCapabilityCapsule(
        owner_profile_ref=owner_profile_ref,
        source_provider=_aggregate_provider(activities),
        source_path=_aggregate_source_path(activities),
        sha256=aggregate_sha256([activity.sha256 for activity in activities]),
        activity_count=len(activities),
        capability_vector=vector,
        match_visibility=_match_visibility_policy(len(activities)),
        confidence=confidence,
        data_quality=data_quality,
        limitations=[
            "first-slice vector uses coarse activity summaries only",
            "heart-rate evidence is treated as noisy context",
            "route-effort units in this slice normalize distance, ascent, and descent only; altitude, pack load, technical terrain, season, weather, daylight, traffic, cost, road condition, and equipment remain human-review context",
            "capability capsule is not route approval and must not replace GPX, structured route, retreat-gate, weather, or equipment review",
            "capsule excludes raw health payloads, raw tracks, exact timestamps, and home/work traces",
        ],
    )


def build_companion_capability_capsule_from_timeline(
    timeline: dict,
    *,
    owner_profile_ref: str = "local_user.private",
) -> CompanionCapabilityCapsule:
    summary = timeline["summary"]
    source_track = timeline["source_track"]
    moving_hours = (summary.get("moving_time_s") or 0) / 3600.0
    elapsed_hours = (summary.get("elapsed_time_s") or 0) / 3600.0
    distance_m = float(summary.get("distance_m") or 0.0)
    ascent_m = float(summary.get("ascent_m") or 0.0)
    descent_m = float(summary.get("descent_m") or 0.0)
    effort_units = distance_m / 1000.0 + ascent_m / 100.0 + descent_m / 200.0
    rest_intervals = timeline.get("rest_intervals", [])
    edges = timeline.get("edges", [])
    vector = CompanionCapabilityVector(
        route_effort_adjusted_moving_pace=round(((summary.get("moving_time_s") or 0) / 60.0) / effort_units, 3)
        if effort_units
        else 0.0,
        ascent_endurance_index=round((ascent_m / moving_hours) / 300.0, 3)
        if moving_hours and ascent_m
        else 0.0,
        descent_conservatism_index=round(300.0 / (descent_m / moving_hours), 3)
        if moving_hours and descent_m
        else 1.0,
        rest_frequency_per_hour=round(len(rest_intervals) / elapsed_hours, 3) if elapsed_hours else 0.0,
        median_rest_duration_min=round(_median([rest["duration_s"] / 60.0 for rest in rest_intervals]), 2),
        late_activity_fatigue_decay=_timeline_fatigue_decay(edges),
        heart_rate_load_per_effort_unit=0.0,
    )
    confidence = _timeline_confidence(edges)
    data_quality = ScoutEnergyDataQuality(
        heart_rate_confidence="low",
        gps_confidence=confidence,
        missing_hr_seconds=0,
        provider_value_confidence="low",
        limitations=[
            "companion vector derived from post-analysis capability timeline only",
            "heart-rate load is unavailable in this timeline-derived capsule",
        ],
    )
    return CompanionCapabilityCapsule(
        owner_profile_ref=owner_profile_ref,
        source_provider="post_analysis_capability_timeline",
        source_path=source_track["source_path"],
        sha256=source_track["sha256"],
        source_scope="coarse_completed_route_summary",
        activity_count=1,
        capability_vector=vector,
        match_visibility=_match_visibility_policy(
            1,
            reasons=[
                "timeline-derived capsule represents one completed route",
                "public companion display requires broader local history",
            ],
        ),
        confidence=confidence,
        data_quality=data_quality,
        limitations=[
            "first-slice vector uses coarse post-analysis timeline summary only",
            "route-effort units in this slice normalize distance, ascent, and descent only; altitude, pack load, technical terrain, season, weather, daylight, traffic, cost, road condition, and equipment remain human-review context",
            "capability capsule is not route approval and must not replace GPX, structured route, retreat-gate, weather, or equipment review",
            "capsule excludes raw tracks, exact timestamps, incident details, and private notes",
        ],
    )


def compare_companion_capsules(
    query: CompanionCapabilityCapsule,
    candidate: CompanionCapabilityCapsule,
    *,
    query_profile_ref: str = "local_user.private",
    candidate_profile_ref: str = "shared_capsule.private",
) -> CompanionMatchResult:
    weights = {
        "route_effort_adjusted_moving_pace": 0.25,
        "ascent_endurance_index": 0.2,
        "descent_conservatism_index": 0.15,
        "rest_frequency_per_hour": 0.15,
        "median_rest_duration_min": 0.1,
        "late_activity_fatigue_decay": 0.1,
        "heart_rate_load_per_effort_unit": 0.05,
    }
    query_vector = query.capability_vector.model_dump()
    candidate_vector = candidate.capability_vector.model_dump()
    distance = sqrt(
        sum(weights[name] * _robust_delta(query_vector[name], candidate_vector[name]) ** 2 for name in weights)
    )
    score = round(100 * exp(-distance))
    if score >= 75:
        band = "similar_rhythm"
    elif score >= 50:
        band = "some_mismatch"
    else:
        band = "different_rhythm"
    source_path = f"{query.source_path}+{candidate.source_path}"
    source_sha = aggregate_sha256(
        [
            {
                "query_profile_ref": query_profile_ref,
                "candidate_profile_ref": candidate_profile_ref,
                "query_sha256": query.sha256,
                "candidate_sha256": candidate.sha256,
                "query_vector": query_vector,
                "candidate_vector": candidate_vector,
            }
        ]
    )
    return CompanionMatchResult(
        source_provider="companion_capability_capsule",
        source_path=source_path,
        sha256=source_sha,
        query_profile_ref=query_profile_ref,
        candidate_profile_ref=candidate_profile_ref,
        match_score=score,
        match_band=band,
        explanations=[
            "weighted normalized distance over coarse capability vector",
            *_match_explanations(query_vector, candidate_vector),
        ],
        mismatch_notes=_mismatch_notes(query_vector, candidate_vector, band),
        data_quality=_combine_capsule_data_quality([query, candidate]),
    )


def build_companion_match_review_artifact(
    query: CompanionCapabilityCapsule,
    candidates: list[CompanionCapabilityCapsule],
    *,
    query_profile_ref: str = "local_user.private",
    candidate_profile_refs: list[str] | None = None,
    review_score_threshold: int = 75,
) -> CompanionMatchReviewArtifact:
    if candidate_profile_refs is not None and len(candidate_profile_refs) != len(candidates):
        raise ValueError("candidate_profile_refs length must match candidates length")
    refs = candidate_profile_refs or [
        candidate.owner_profile_ref or f"shared_capsule.{index + 1}"
        for index, candidate in enumerate(candidates)
    ]
    matches = [
        compare_companion_capsules(
            query,
            candidate,
            query_profile_ref=query_profile_ref,
            candidate_profile_ref=ref,
        )
        for candidate, ref in zip(candidates, refs)
    ]
    ranked_matches = sorted(
        matches,
        key=lambda match: (-match.match_score, match.candidate_profile_ref),
    )
    source_path = _aggregate_capsule_source_path([query, *candidates])
    source_sha = aggregate_sha256(
        [
            {
                "query_profile_ref": query_profile_ref,
                "query_sha256": query.sha256,
                "candidate_refs": refs,
                "candidate_sha256": [candidate.sha256 for candidate in candidates],
                "ranked_match_sha256": [match.sha256 for match in ranked_matches],
                "review_score_threshold": review_score_threshold,
            }
        ]
    )
    return CompanionMatchReviewArtifact(
        source_path=source_path,
        sha256=source_sha,
        query_profile_ref=query_profile_ref,
        candidate_count=len(candidates),
        ranked_matches=ranked_matches,
        recommended_review_refs=[
            match.candidate_profile_ref
            for match in ranked_matches
            if match.match_score < review_score_threshold
        ],
        review_policy={
            "score_threshold": review_score_threshold,
            "ranking": "match_score_desc_then_candidate_ref",
            "minimum_activity_count_for_public_match": 3,
            "query_activity_count": query.activity_count,
            "query_public_match_display_allowed": query.match_visibility.public_match_display_allowed,
            "candidate_activity_counts": {
                ref: candidate.activity_count
                for ref, candidate in zip(refs, candidates)
            },
            "candidate_review_only_refs": [
                ref
                for ref, candidate in zip(refs, candidates)
                if candidate.match_visibility.review_only
            ],
            "human_review_required_for_mismatch": True,
            "planning_use_only_after_review": True,
            "auto_departure_approval_allowed": False,
            "runtime_safety_truth": False,
        },
        data_quality=_combine_capsule_data_quality([query, *candidates]),
        limitations=[
            "rankings compare coarse pacing and rest-rhythm vectors only",
            "match score is not a safety guarantee, medical assessment, or fitness diagnosis",
            "candidate capsules must remain privacy-preserving summaries without raw tracks, exact timestamps, or raw health payloads",
        ],
    )


def write_companion_match_review_artifact(
    artifact: CompanionMatchReviewArtifact,
    output_path: Path,
) -> CompanionMatchReviewArtifact:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(artifact.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return artifact


def build_companion_pool_entry(
    capsule: CompanionCapabilityCapsule,
    *,
    public_profile_ref: str,
    explicit_consent: bool,
    allow_public_match_display: bool | None = None,
) -> CompanionPoolEntry:
    if not explicit_consent:
        raise ValueError("explicit consent is required before adding a capsule to the companion pool")
    _assert_pool_capsule_boundary(capsule)
    resolved_public_display = (
        capsule.match_visibility.public_match_display_allowed
        if allow_public_match_display is None
        else allow_public_match_display and capsule.match_visibility.public_match_display_allowed
    )
    consent = CompanionPoolConsentPolicy(
        explicit_consent=True,
        allow_public_match_display=resolved_public_display,
    )
    visibility = CompanionMatchVisibilityPolicy(
        minimum_activity_count=capsule.match_visibility.minimum_activity_count,
        activity_count=capsule.activity_count,
        public_match_display_allowed=resolved_public_display,
        review_only=not resolved_public_display,
        reasons=[
            *capsule.match_visibility.reasons,
            "capsule entered local companion pool only after explicit consent",
            "remote upload is not allowed by this local alpha consent policy",
        ],
    )
    source_sha = aggregate_sha256(
        [
            {
                "capsule_sha256": capsule.sha256,
                "public_profile_ref": public_profile_ref,
                "consent": consent.model_dump(mode="json"),
                "visibility": visibility.model_dump(mode="json"),
            }
        ]
    )
    return CompanionPoolEntry(
        source_path=capsule.source_path,
        sha256=source_sha,
        owner_profile_ref=capsule.owner_profile_ref,
        public_profile_ref=public_profile_ref,
        capsule=capsule,
        consent=consent,
        match_visibility=visibility,
        data_quality=capsule.data_quality,
        limitations=[
            "local consent pool stores privacy-preserving capability capsules only",
            "raw tracks, exact timestamps, raw health payloads, route-family names, and remote upload are excluded",
            "pool presence is not a safety guarantee or medical assessment",
        ],
    )


def build_companion_consent_pool(
    entries: list[CompanionPoolEntry],
    *,
    source_path: str = "local_companion_consent_pool",
) -> CompanionConsentPoolArtifact:
    unique_refs = {entry.public_profile_ref for entry in entries}
    if len(unique_refs) != len(entries):
        raise ValueError("public_profile_ref values must be unique in a companion consent pool")
    return CompanionConsentPoolArtifact(
        source_path=source_path,
        sha256=aggregate_sha256(
            [
                {
                    "source_path": source_path,
                    "entry_sha256": [entry.sha256 for entry in entries],
                    "entry_refs": [entry.public_profile_ref for entry in entries],
                }
            ]
        ),
        entry_count=len(entries),
        entries=entries,
        data_quality=_combine_pool_entry_data_quality(entries),
        limitations=[
            "local-only pool artifact; no remote or community upload is performed",
            "entries require explicit consent and may be withdrawn locally",
            "matching uses coarse capability capsules only",
        ],
    )


def withdraw_companion_pool_entry(
    pool: CompanionConsentPoolArtifact,
    *,
    public_profile_ref: str,
) -> CompanionConsentPoolArtifact:
    remaining = [entry for entry in pool.entries if entry.public_profile_ref != public_profile_ref]
    if len(remaining) == len(pool.entries):
        raise ValueError(f"companion pool entry not found: {public_profile_ref}")
    return build_companion_consent_pool(remaining, source_path=pool.source_path)


def build_companion_match_review_from_pool(
    query: CompanionCapabilityCapsule,
    pool: CompanionConsentPoolArtifact,
    *,
    query_profile_ref: str = "local_user.private",
    include_review_only: bool = False,
    review_score_threshold: int = 75,
) -> CompanionMatchReviewArtifact:
    entries = [
        entry
        for entry in pool.entries
        if include_review_only or entry.match_visibility.public_match_display_allowed
    ]
    artifact = build_companion_match_review_artifact(
        query,
        [entry.capsule for entry in entries],
        query_profile_ref=query_profile_ref,
        candidate_profile_refs=[entry.public_profile_ref for entry in entries],
        review_score_threshold=review_score_threshold,
    )
    artifact.review_policy.update(
        {
            "source_pool_ref": pool.source_path,
            "source_pool_sha256": pool.sha256,
            "pool_entry_count": pool.entry_count,
            "pool_remote_upload_allowed": False,
            "include_review_only_pool_entries": include_review_only,
            "withdrawal_supported": True,
        }
    )
    artifact.limitations.append("candidate capsules came from a local explicit-consent pool")
    return artifact


def write_companion_consent_pool_artifact(
    artifact: CompanionConsentPoolArtifact,
    output_path: Path,
) -> CompanionConsentPoolArtifact:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(artifact.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return artifact


def build_companion_pool_exchange_package(
    pool: CompanionConsentPoolArtifact,
    *,
    public_profile_refs: list[str] | None = None,
    source_path: str = "local_companion_pool_exchange_package",
) -> CompanionPoolExchangePackage:
    refs = set(public_profile_refs or [])
    entries = [
        entry
        for entry in pool.entries
        if public_profile_refs is None or entry.public_profile_ref in refs
    ]
    if public_profile_refs is not None and len(entries) != len(refs):
        found = {entry.public_profile_ref for entry in entries}
        missing = sorted(refs - found)
        raise ValueError(f"companion pool entries not found for exchange package: {missing}")
    for entry in entries:
        _assert_pool_entry_boundary(entry)
    return CompanionPoolExchangePackage(
        source_path=source_path,
        sha256=aggregate_sha256(
            [
                {
                    "source_pool_sha256": pool.sha256,
                    "source_path": source_path,
                    "entry_sha256": [entry.sha256 for entry in entries],
                    "entry_refs": [entry.public_profile_ref for entry in entries],
                    "package_scope": "manual_local_exchange",
                }
            ]
        ),
        entry_count=len(entries),
        entries=entries,
        data_quality=_combine_pool_entry_data_quality(entries),
        limitations=[
            "manual local exchange package only; no remote upload is performed",
            "package contains explicit-consent pool entries and privacy-preserving capsules only",
            "receiver import still creates a local-only consent pool artifact",
        ],
    )


def import_companion_pool_exchange_package(
    package: CompanionPoolExchangePackage,
    *,
    existing_pool: CompanionConsentPoolArtifact | None = None,
    source_path: str = "imported_local_companion_consent_pool",
) -> CompanionConsentPoolArtifact:
    if package.remote_upload_allowed:
        raise ValueError("remote-upload companion exchange packages are not supported")
    for entry in package.entries:
        _assert_pool_entry_boundary(entry)
    entries = list(existing_pool.entries) if existing_pool else []
    existing_refs = {entry.public_profile_ref for entry in entries}
    for entry in package.entries:
        if entry.public_profile_ref in existing_refs:
            raise ValueError(f"duplicate companion pool entry: {entry.public_profile_ref}")
        entries.append(entry)
        existing_refs.add(entry.public_profile_ref)
    return build_companion_consent_pool(entries, source_path=source_path)


def build_companion_community_publish_dry_run(
    pool: CompanionConsentPoolArtifact,
    *,
    public_profile_refs: list[str] | None = None,
    community_ref: str,
    explicit_community_consent: bool,
    source_path: str = "companion_community_publish_dry_run",
) -> CompanionCommunityPublishDryRun:
    if not explicit_community_consent:
        raise ValueError("explicit community consent is required before community publish dry-run")
    refs = set(public_profile_refs or [])
    entries = [
        entry
        for entry in pool.entries
        if public_profile_refs is None or entry.public_profile_ref in refs
    ]
    if public_profile_refs is not None and len(entries) != len(refs):
        found = {entry.public_profile_ref for entry in entries}
        missing = sorted(refs - found)
        raise ValueError(f"companion pool entries not found for community dry-run: {missing}")
    for entry in entries:
        _assert_pool_entry_boundary(entry)
        if not entry.match_visibility.public_match_display_allowed:
            raise ValueError(f"companion pool entry is review-only and cannot be community-publishable: {entry.public_profile_ref}")
    publish_entries = [_community_publish_entry_from_pool_entry(entry) for entry in entries]
    return CompanionCommunityPublishDryRun(
        source_path=source_path,
        sha256=aggregate_sha256(
            [
                {
                    "source_pool_sha256": pool.sha256,
                    "source_path": source_path,
                    "community_ref": community_ref,
                    "entry_sha256": [entry.sha256 for entry in publish_entries],
                    "entry_refs": [entry.public_profile_ref for entry in publish_entries],
                    "publish_mode": "dry_run_only",
                    "network_request_performed": False,
                    "remote_upload_performed": False,
                }
            ]
        ),
        community_ref=community_ref,
        explicit_community_consent=True,
        entry_count=len(publish_entries),
        entries=publish_entries,
        data_quality=_combine_pool_entry_data_quality(entries),
        limitations=[
            "community publish dry-run only; no remote upload is performed",
            "network transport and remote community service are not implemented in this artifact",
            "entries remain privacy-preserving capability capsules without raw tracks, exact timestamps, raw health payloads, or route-family names",
            "community publication is not a safety guarantee, medical assessment, or fitness ranking",
        ],
    )


def _community_publish_entry_from_pool_entry(entry: CompanionPoolEntry) -> CompanionCommunityPublishEntry:
    source_sha = aggregate_sha256(
        [
            {
                "public_profile_ref": entry.public_profile_ref,
                "source_pool_entry_sha256": entry.sha256,
                "capability_vector": entry.capsule.capability_vector.model_dump(mode="json"),
                "activity_count": entry.capsule.activity_count,
                "match_visibility": entry.match_visibility.model_dump(mode="json"),
            }
        ]
    )
    return CompanionCommunityPublishEntry(
        public_profile_ref=entry.public_profile_ref,
        sha256=source_sha,
        source_pool_entry_sha256=entry.sha256,
        source_provider=entry.capsule.source_provider,
        source_scope=entry.capsule.source_scope,
        activity_count=entry.capsule.activity_count,
        capability_vector=entry.capsule.capability_vector,
        match_visibility=entry.match_visibility,
        confidence=entry.capsule.confidence,
        data_quality=entry.data_quality,
        limitations=[
            "community dry-run publish entry is projected from a local explicit-consent pool entry",
            "private owner profile refs, local consent metadata, raw tracks, raw health payloads, exact timestamps, and route-family names are excluded",
        ],
    )


def write_companion_community_publish_dry_run(
    artifact: CompanionCommunityPublishDryRun,
    output_path: Path,
) -> CompanionCommunityPublishDryRun:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(artifact.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return artifact


def write_companion_pool_exchange_package(
    package: CompanionPoolExchangePackage,
    output_path: Path,
) -> CompanionPoolExchangePackage:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(package.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return package


def _capability_vector(activities: list[WearableActivitySummary]) -> CompanionCapabilityVector:
    effort_units = [_route_effort_units(activity) for activity in activities]
    moving_minutes = [activity.moving_time_s / 60.0 for activity in activities]
    moving_pace = _mean([minutes / effort for minutes, effort in zip(moving_minutes, effort_units) if effort > 0])
    ascent_rates = [
        activity.ascent_m / (activity.moving_time_s / 3600.0)
        for activity in activities
        if activity.ascent_m > 0 and activity.moving_time_s > 0
    ]
    descent_rates = [
        activity.descent_m / (activity.moving_time_s / 3600.0)
        for activity in activities
        if activity.descent_m > 0 and activity.moving_time_s > 0
    ]
    rest_hours = sum(activity.duration_s for activity in activities) / 3600.0
    rest_frequency = sum(activity.rest_event_count for activity in activities) / rest_hours if rest_hours else 0.0
    rest_durations = sorted(duration for activity in activities for duration in activity.rest_duration_min)
    fatigue_values = [activity.late_activity_fatigue_decay for activity in activities if activity.late_activity_fatigue_decay is not None]
    hr_load_per_effort = _mean(
        [internal_load_score(activity) / effort for activity, effort in zip(activities, effort_units) if effort > 0]
    )
    return CompanionCapabilityVector(
        route_effort_adjusted_moving_pace=round(moving_pace, 3),
        ascent_endurance_index=round((_mean(ascent_rates) or 0.0) / 300.0, 3),
        descent_conservatism_index=round(300.0 / (_mean(descent_rates) or 300.0), 3),
        rest_frequency_per_hour=round(rest_frequency, 3),
        median_rest_duration_min=round(_median(rest_durations), 2),
        late_activity_fatigue_decay=round(_mean(fatigue_values), 3),
        heart_rate_load_per_effort_unit=round(hr_load_per_effort, 3),
    )


def _match_visibility_policy(
    activity_count: int,
    *,
    minimum_activity_count: int = 3,
    reasons: list[str] | None = None,
) -> CompanionMatchVisibilityPolicy:
    public_allowed = activity_count >= minimum_activity_count
    resolved_reasons = list(reasons or [])
    if public_allowed:
        resolved_reasons.append("minimum local activity count satisfied for alpha companion match display")
    else:
        resolved_reasons.append(
            f"needs at least {minimum_activity_count} local activities before public companion match display"
        )
    return CompanionMatchVisibilityPolicy(
        minimum_activity_count=minimum_activity_count,
        activity_count=activity_count,
        public_match_display_allowed=public_allowed,
        review_only=not public_allowed,
        reasons=resolved_reasons,
    )


def _route_effort_units(activity: WearableActivitySummary) -> float:
    return activity.distance_m / 1000.0 + activity.ascent_m / 100.0 + activity.descent_m / 200.0


def _capsule_data_quality(activities: list[WearableActivitySummary]) -> ScoutEnergyDataQuality:
    order = {"low": 0, "medium": 1, "high": 2}
    return ScoutEnergyDataQuality(
        heart_rate_confidence=min((activity.data_quality.heart_rate_confidence for activity in activities), key=order.get),
        gps_confidence=min((activity.data_quality.gps_confidence for activity in activities), key=order.get),
        missing_hr_seconds=sum(activity.data_quality.missing_hr_seconds for activity in activities),
        provider_value_confidence=min(
            (activity.data_quality.provider_value_confidence for activity in activities),
            key=order.get,
        ),
        limitations=sorted({limitation for activity in activities for limitation in activity.data_quality.limitations}),
    )


def _aggregate_provider(activities: list[WearableActivitySummary]) -> str:
    providers = sorted({activity.source_provider for activity in activities})
    return providers[0] if len(providers) == 1 else "mixed_wearable_activity_summaries"


def _aggregate_source_path(activities: list[WearableActivitySummary]) -> str:
    paths = sorted({activity.source_path for activity in activities})
    if len(paths) == 1:
        return paths[0]
    split_paths = [path.split("/")[:-1] for path in paths]
    prefix: list[str] = []
    for parts in zip(*split_paths):
        if len(set(parts)) != 1:
            break
        prefix.append(parts[0])
    return f"aggregate:{'/'.join(prefix) if prefix else 'wearable_activity_summaries'}"


def _aggregate_capsule_source_path(capsules: list[CompanionCapabilityCapsule]) -> str:
    paths = sorted({capsule.source_path for capsule in capsules})
    if len(paths) == 1:
        return f"aggregate:{paths[0]}"
    split_paths = [path.split("/")[:-1] for path in paths]
    prefix: list[str] = []
    for parts in zip(*split_paths):
        if len(set(parts)) != 1:
            break
        prefix.append(parts[0])
    return f"aggregate:{'/'.join(prefix) if prefix else 'companion_capability_capsules'}"


def _combine_capsule_data_quality(
    capsules: list[CompanionCapabilityCapsule],
) -> ScoutEnergyDataQuality:
    if not capsules:
        return ScoutEnergyDataQuality()
    order = {"low": 0, "medium": 1, "high": 2}
    return ScoutEnergyDataQuality(
        heart_rate_confidence=min(
            (capsule.data_quality.heart_rate_confidence for capsule in capsules),
            key=order.get,
        ),
        gps_confidence=min(
            (capsule.data_quality.gps_confidence for capsule in capsules),
            key=order.get,
        ),
        missing_hr_seconds=sum(capsule.data_quality.missing_hr_seconds for capsule in capsules),
        provider_value_confidence=min(
            (capsule.data_quality.provider_value_confidence for capsule in capsules),
            key=order.get,
        ),
        limitations=sorted(
            {
                limitation
                for capsule in capsules
                for limitation in capsule.data_quality.limitations
            }
        ),
    )


def _combine_pool_entry_data_quality(
    entries: list[CompanionPoolEntry],
) -> ScoutEnergyDataQuality:
    if not entries:
        return ScoutEnergyDataQuality(
            limitations=["empty local companion consent pool"],
        )
    order = {"low": 0, "medium": 1, "high": 2}
    return ScoutEnergyDataQuality(
        heart_rate_confidence=min(
            (entry.data_quality.heart_rate_confidence for entry in entries),
            key=order.get,
        ),
        gps_confidence=min(
            (entry.data_quality.gps_confidence for entry in entries),
            key=order.get,
        ),
        missing_hr_seconds=sum(entry.data_quality.missing_hr_seconds for entry in entries),
        provider_value_confidence=min(
            (entry.data_quality.provider_value_confidence for entry in entries),
            key=order.get,
        ),
        limitations=sorted(
            {
                limitation
                for entry in entries
                for limitation in entry.data_quality.limitations
            }
        ),
    )


def _assert_pool_capsule_boundary(capsule: CompanionCapabilityCapsule) -> None:
    if capsule.raw_track_shared or capsule.raw_health_payload_shared or capsule.exact_timestamps_shared:
        raise ValueError("companion pool entries cannot share raw tracks, raw health payloads, or exact timestamps")
    if capsule.privacy.raw_track_shared or capsule.privacy.raw_health_payload_shared:
        raise ValueError("companion pool entries cannot share raw privacy-sensitive payloads")
    if capsule.privacy.exact_timestamps_shared or capsule.privacy.home_work_trace_shared:
        raise ValueError("companion pool entries cannot share exact timestamps or home/work traces")
    if capsule.boundary.medical_diagnosis:
        raise ValueError("companion pool entries cannot be medical diagnosis")
    if capsule.boundary.phase1_runtime_safety_truth or capsule.boundary.safety_api_calls_allowed:
        raise ValueError("companion pool entries cannot be Phase 1 safety truth or allow safety API calls")


def _assert_pool_entry_boundary(entry: CompanionPoolEntry) -> None:
    if not entry.consent.explicit_consent:
        raise ValueError("companion pool exchange entries require explicit consent")
    if entry.consent.remote_upload_allowed:
        raise ValueError("companion pool exchange entries cannot allow remote upload")
    if entry.consent.route_family_names_shared:
        raise ValueError("companion pool exchange entries cannot share route-family names")
    if entry.consent.raw_track_shared or entry.consent.raw_health_payload_shared:
        raise ValueError("companion pool exchange entries cannot share raw tracks or raw health payloads")
    if entry.consent.exact_timestamps_shared:
        raise ValueError("companion pool exchange entries cannot share exact timestamps")
    _assert_pool_capsule_boundary(entry.capsule)


def _match_explanations(
    query_vector: dict[str, float],
    candidate_vector: dict[str, float],
) -> list[str]:
    explanations: list[str] = []
    if abs(_robust_delta(query_vector["route_effort_adjusted_moving_pace"], candidate_vector["route_effort_adjusted_moving_pace"])) >= 0.25:
        explanations.append("route effort-adjusted moving pace differs enough for planning review")
    if abs(_robust_delta(query_vector["rest_frequency_per_hour"], candidate_vector["rest_frequency_per_hour"])) >= 0.25:
        explanations.append("rest rhythm differs enough for planning review")
    if abs(_robust_delta(query_vector["late_activity_fatigue_decay"], candidate_vector["late_activity_fatigue_decay"])) >= 0.25:
        explanations.append("late-activity pacing decay differs enough for planning review")
    return explanations


def _mismatch_notes(
    query_vector: dict[str, float],
    candidate_vector: dict[str, float],
    band: str,
) -> list[str]:
    if band == "similar_rhythm":
        return []
    notes = ["review pacing and rest rhythm before using this as planning context"]
    if candidate_vector["route_effort_adjusted_moving_pace"] > query_vector["route_effort_adjusted_moving_pace"]:
        notes.append("candidate summary trends toward slower effort-adjusted moving pace")
    elif candidate_vector["route_effort_adjusted_moving_pace"] < query_vector["route_effort_adjusted_moving_pace"]:
        notes.append("candidate summary trends toward faster effort-adjusted moving pace")
    if candidate_vector["rest_frequency_per_hour"] > query_vector["rest_frequency_per_hour"]:
        notes.append("candidate summary trends toward more frequent rests")
    elif candidate_vector["rest_frequency_per_hour"] < query_vector["rest_frequency_per_hour"]:
        notes.append("candidate summary trends toward fewer rests")
    return notes


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _median(values: list[float]) -> float:
    if not values:
        return 0.0
    midpoint = len(values) // 2
    if len(values) % 2:
        return values[midpoint]
    return (values[midpoint - 1] + values[midpoint]) / 2.0


def _timeline_confidence(edges: list[dict]) -> Confidence:
    values = [edge.get("confidence", "low") for edge in edges]
    if not values:
        return "low"
    order = {"low": 0, "medium": 1, "high": 2}
    return min(values, key=lambda value: order.get(value, 0))


def _timeline_fatigue_decay(edges: list[dict]) -> float:
    if len(edges) < 2:
        return 0.0
    midpoint = len(edges) // 2
    early = _edge_pace(edges[:midpoint])
    late = _edge_pace(edges[-midpoint:])
    if early <= 0:
        return 0.0
    return round((late / early) - 1.0, 3)


def _edge_pace(edges: list[dict]) -> float:
    effort = sum(
        (edge.get("distance_m") or 0.0) / 1000.0
        + (edge.get("ascent_m") or 0.0) / 100.0
        + (edge.get("descent_m") or 0.0) / 200.0
        for edge in edges
    )
    moving_minutes = sum((edge.get("moving_time_s") or 0) / 60.0 for edge in edges)
    return moving_minutes / effort if effort else 0.0


def _robust_delta(a: float, b: float) -> float:
    scale = max(abs(a), abs(b), 1.0)
    return (a - b) / scale
