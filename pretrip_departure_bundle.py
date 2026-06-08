from __future__ import annotations

import json
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from pretrip_artifact_manifest import build_pretrip_artifact_manifest


DEFAULT_CHILAI_PROJECT_REF = (
    "tests/fixtures/pretrip/projects/chilai_nanhua_day1/project.json"
)


class DepartureBundleStatus(StrEnum):
    CANDIDATE = "candidate"
    FROZEN_CANDIDATE = "frozen_candidate"


class StrictDepartureModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DeparturePackageSummary(StrictDepartureModel):
    package_id: str
    project_id: str
    version: str
    status: str
    reviewed_package_ref: str
    source_artifact_count: int = Field(ge=0)
    checkpoint_candidate_count: int = Field(ge=0)
    segment_candidate_count: int = Field(ge=0)
    retreat_route_candidate_count: int = Field(ge=0)


class DepartureRef(StrictDepartureModel):
    ref_key: str
    ref: str
    sha256: str
    exists: Literal[True] = True
    status: str | None = None
    summary: dict[str, Any] = Field(default_factory=dict)


class SourceChecksumSummary(StrictDepartureModel):
    artifact_kind: str
    artifact_id: str
    sha256: str
    media_type: str | None = None
    size_bytes: int | None = Field(default=None, ge=0)


class DepartureArtifactManifestSummary(StrictDepartureModel):
    project_artifact_count: int = Field(ge=0)
    source_artifact_count: int = Field(ge=0)
    total_artifact_count: int = Field(ge=0)
    missing_ref_count: Literal[0] = 0
    project_ref_hashes: list[DepartureRef] = Field(default_factory=list)
    source_checksum_summaries: list[SourceChecksumSummary] = Field(default_factory=list)


class DepartureBundleCounts(StrictDepartureModel):
    required_ref_count: int = Field(ge=0)
    source_checksum_count: int = Field(ge=0)
    readiness_finding_count: int = Field(ge=0)
    remote_conservative_note_count: int = Field(ge=0)
    resource_warning_candidate_count: int = Field(ge=0)
    resource_blocker_candidate_count: int = Field(ge=0)
    route_ref_count: int = Field(ge=0)
    terrain_ref_count: int = Field(ge=0)
    audit_ref_count: int = Field(ge=0)


class DepartureBoundary(StrictDepartureModel):
    human_review_required_before_departure: Literal[True] = True
    not_departure_approval: Literal[True] = True
    fixture_first: Literal[True] = True
    external_api_calls_made: Literal[False] = False
    raw_payloads_embedded: Literal[False] = False
    phase1_runtime_mutation_allowed: Literal[False] = False
    phase2_writeback_allowed: Literal[False] = False
    notes: list[str] = Field(default_factory=list)


class PreTripDepartureBundleManifest(StrictDepartureModel):
    bundle_id: str
    artifact_kind: Literal["pretrip_departure_bundle_manifest"] = (
        "pretrip_departure_bundle_manifest"
    )
    project_id: str
    status: DepartureBundleStatus = DepartureBundleStatus.FROZEN_CANDIDATE
    package: DeparturePackageSummary
    reviewed_mission_graph: DepartureRef
    readiness_refs: list[DepartureRef] = Field(default_factory=list)
    remote_summary: DepartureRef
    resource_plan: DepartureRef
    route_refs: list[DepartureRef] = Field(default_factory=list)
    terrain_refs: list[DepartureRef] = Field(default_factory=list)
    audit_refs: list[DepartureRef] = Field(default_factory=list)
    artifact_manifest: DepartureArtifactManifestSummary
    counts: DepartureBundleCounts
    boundary: DepartureBoundary = Field(default_factory=DepartureBoundary)
    release_gate_compatibility_notes: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def enforce_handoff_boundary(self) -> "PreTripDepartureBundleManifest":
        if self.status not in {
            DepartureBundleStatus.CANDIDATE,
            DepartureBundleStatus.FROZEN_CANDIDATE,
        }:
            raise ValueError("departure bundle status must stay candidate-scoped")
        if self.artifact_manifest.missing_ref_count != 0:
            raise ValueError("departure bundle requires all referenced artifacts to exist")
        _assert_no_raw_payload_fragments(self.model_dump(mode="json"))
        return self

    def to_json(self) -> str:
        return json.dumps(
            self.model_dump(mode="json"),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        ) + "\n"


def build_chilai_departure_bundle(
    project_root: Path | str,
) -> PreTripDepartureBundleManifest:
    project_path = _resolve_chilai_project_path(Path(project_root))
    fixture_root = project_path.parent
    project = _load_json(project_path)
    reviewed_package = _load_json(fixture_root / project["reviewed_package_ref"])
    raw_artifact_manifest = build_pretrip_artifact_manifest(project_path).to_dict()
    artifact_manifest = _departure_artifact_manifest_view(raw_artifact_manifest)

    if artifact_manifest["counts"]["missing_refs"] != 0:
        raise ValueError("departure bundle requires a complete artifact manifest")

    artifact_by_ref_key = {
        artifact["ref_key"]: artifact
        for artifact in artifact_manifest["artifacts"]
        if artifact.get("source") == "project" and not artifact.get("missing")
    }

    readiness_refs = [
        _required_ref(artifact_by_ref_key, "readiness_report_ref"),
        _required_ref(artifact_by_ref_key, "plan_validation_candidates_ref"),
        _required_ref(artifact_by_ref_key, "poi_readiness_candidates_ref"),
        _required_ref(artifact_by_ref_key, "segment_policy_candidates_ref"),
        _required_ref(artifact_by_ref_key, "weather_daylight_evidence_ref"),
    ]
    route_refs = [
        _required_ref(artifact_by_ref_key, "route_summary_ref"),
        _required_ref(artifact_by_ref_key, "route_comparison_ref"),
        _required_ref(artifact_by_ref_key, "checkpoint_candidates_ref"),
        _required_ref(artifact_by_ref_key, "segment_candidates_ref"),
        _required_ref(artifact_by_ref_key, "retreat_routes_ref"),
        _required_ref(artifact_by_ref_key, "map_context_ref"),
        _required_ref(artifact_by_ref_key, "map_candidates_ref"),
    ]
    terrain_refs = [
        _required_ref(artifact_by_ref_key, "dtm_coverage_summary_ref"),
        _required_ref(artifact_by_ref_key, "segment_dtm_coverage_ref"),
        _required_ref(artifact_by_ref_key, "contour_interpretation_candidates_ref"),
    ]
    audit_refs = [
        _required_ref(artifact_by_ref_key, "human_reviews_ref"),
        _required_ref(artifact_by_ref_key, "review_draft_log_ref"),
        _required_ref(artifact_by_ref_key, "planning_skill_audit_ref"),
        _required_ref(artifact_by_ref_key, "runtime_audit_manifest_ref"),
        _required_ref(artifact_by_ref_key, "after_action_next_plan_candidates_ref"),
        _required_ref(artifact_by_ref_key, "brain_seed_nodes_ref"),
    ]

    remote_summary = _required_ref(artifact_by_ref_key, "remote_contact_summary_ref")
    resource_plan = _required_ref(artifact_by_ref_key, "resource_plan_ref")
    reviewed_mission_graph = _required_ref(
        artifact_by_ref_key,
        "compiled_mission_graph_reviewed_ref",
    )

    project_ref_hashes = [
        _ref_hash_summary(artifact)
        for artifact in artifact_manifest["artifacts"]
        if artifact.get("source") == "project" and not artifact.get("missing")
    ]
    source_checksums = [
        _source_checksum_summary(artifact)
        for artifact in artifact_manifest["artifacts"]
        if artifact.get("source") == "pretrip_package"
    ]

    readiness_report = _load_json(fixture_root / project["readiness_report_ref"])
    remote_payload = _load_json(fixture_root / project["remote_contact_summary_ref"])
    resource_payload = _load_json(fixture_root / project["resource_plan_ref"])
    departure = resource_payload.get("departure_readiness_context", {})

    return PreTripDepartureBundleManifest(
        bundle_id="departure_bundle.chilai_nanhua_day1.v0",
        project_id=project["project_id"],
        package=DeparturePackageSummary(
            package_id=reviewed_package["package_id"],
            project_id=reviewed_package["project_id"],
            version=reviewed_package["version"],
            status=reviewed_package["status"],
            reviewed_package_ref=project["reviewed_package_ref"],
            source_artifact_count=len(reviewed_package.get("source_artifacts", [])),
            checkpoint_candidate_count=len(reviewed_package.get("checkpoint_candidates", [])),
            segment_candidate_count=len(reviewed_package.get("segment_candidates", [])),
            retreat_route_candidate_count=len(
                reviewed_package.get("retreat_route_candidates", [])
            ),
        ),
        reviewed_mission_graph=reviewed_mission_graph,
        readiness_refs=readiness_refs,
        remote_summary=remote_summary,
        resource_plan=resource_plan,
        route_refs=route_refs,
        terrain_refs=terrain_refs,
        audit_refs=audit_refs,
        artifact_manifest=DepartureArtifactManifestSummary(
            project_artifact_count=artifact_manifest["counts"]["project_artifacts"],
            source_artifact_count=artifact_manifest["counts"]["source_artifacts"],
            total_artifact_count=artifact_manifest["counts"]["total_artifacts"],
            missing_ref_count=artifact_manifest["counts"]["missing_refs"],
            project_ref_hashes=project_ref_hashes,
            source_checksum_summaries=source_checksums,
        ),
        counts=DepartureBundleCounts(
            required_ref_count=(
                1
                + len(readiness_refs)
                + 1
                + 1
                + len(route_refs)
                + len(terrain_refs)
                + len(audit_refs)
            ),
            source_checksum_count=len(source_checksums),
            readiness_finding_count=len(readiness_report.get("findings", [])),
            remote_conservative_note_count=len(remote_payload.get("conservative_notes", [])),
            resource_warning_candidate_count=len(departure.get("warning_candidates", [])),
            resource_blocker_candidate_count=len(departure.get("blocker_candidates", [])),
            route_ref_count=len(route_refs),
            terrain_ref_count=len(terrain_refs),
            audit_ref_count=len(audit_refs),
        ),
        boundary=DepartureBoundary(
            notes=[
                "Field-trial handoff manifest only; it does not approve real departure.",
                "All refs point at fixture-reviewed or candidate planning artifacts.",
                "Review draft log refs are audit-only draft pointers and are not departure approval.",
                "Phase 1 runtime and Phase 2 writeback stores are not mutated by this builder.",
                "Raw GPX, JPG, DTM, and incident/sample payloads are excluded.",
            ],
        ),
        release_gate_compatibility_notes=[
            "Integrated into the Phase 4 release gate as an additive fixture artifact.",
            "The release gate validates project refs, fixture boundaries, MissionGraph compatibility, readiness, resource, remote, runtime-audit, and artifact-manifest checks.",
            "The manifest remains a frozen candidate handoff and does not approve real departure.",
        ],
    )


def load_departure_bundle(path: Path | str) -> PreTripDepartureBundleManifest:
    return PreTripDepartureBundleManifest.model_validate_json(
        Path(path).read_text(encoding="utf-8")
    )


def _departure_artifact_manifest_view(
    artifact_manifest: dict[str, Any],
) -> dict[str, Any]:
    artifacts = [
        artifact
        for artifact in artifact_manifest["artifacts"]
        if artifact.get("ref_key") != "departure_bundle_manifest_ref"
    ]
    return artifact_manifest | {
        "artifacts": artifacts,
        "counts": {
            "total_artifacts": len(artifacts),
            "project_artifacts": sum(
                1 for artifact in artifacts if artifact.get("source") == "project"
            ),
            "source_artifacts": sum(
                1
                for artifact in artifacts
                if artifact.get("source") == "pretrip_package"
            ),
            "missing_refs": sum(
                1 for artifact in artifacts if artifact.get("missing") is True
            ),
        },
    }


def _resolve_chilai_project_path(path: Path) -> Path:
    if path.name == "project.json":
        return path
    if (path / "project.json").exists():
        return path / "project.json"
    repo_fixture = path / DEFAULT_CHILAI_PROJECT_REF
    if repo_fixture.exists():
        return repo_fixture
    raise FileNotFoundError(f"could not find Chilai pretrip project.json under {path}")


def _required_ref(
    artifact_by_ref_key: dict[str, dict[str, Any]],
    ref_key: str,
) -> DepartureRef:
    try:
        artifact = artifact_by_ref_key[ref_key]
    except KeyError as exc:
        raise ValueError(f"missing departure bundle ref: {ref_key}") from exc
    return _ref_hash_summary(artifact)


def _ref_hash_summary(artifact: dict[str, Any]) -> DepartureRef:
    excluded = {"artifact_kind", "ref_key", "source", "ref", "path", "sha256"}
    summary = {
        key: _sanitize_summary_value(value)
        for key, value in artifact.items()
        if key not in excluded and value is not None
        and not _is_raw_payload_pointer(value)
    }
    return DepartureRef(
        ref_key=artifact["ref_key"],
        ref=artifact["ref"],
        sha256=artifact["sha256"],
        status=artifact.get("status"),
        summary=summary,
    )


def _source_checksum_summary(artifact: dict[str, Any]) -> SourceChecksumSummary:
    return SourceChecksumSummary(
        artifact_kind=artifact["artifact_kind"],
        artifact_id=str(artifact["ref"]).replace(".", ":"),
        sha256=artifact["sha256"],
        media_type=artifact.get("media_type"),
        size_bytes=artifact.get("size_bytes"),
    )


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _sanitize_summary_value(value: Any) -> Any:
    if isinstance(value, str):
        return value.replace("artifact.gpx.", "artifact:gpx:").replace(
            "artifact.photo.",
            "artifact:photo:",
        )
    if isinstance(value, list):
        return [_sanitize_summary_value(item) for item in value]
    if isinstance(value, dict):
        return {
            key: _sanitize_summary_value(item)
            for key, item in value.items()
            if not _is_raw_payload_pointer(item)
        }
    return value


def _is_raw_payload_pointer(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    lowered = value.lower()
    return any(
        fragment in lowered
        for fragment in (
            ".gpx",
            ".grd",
            ".hdr",
            ".jpg",
            ".jpeg",
            ".tif",
            ".tiff",
            "catographydata",
            "pdrsample",
        )
    )


def _assert_no_raw_payload_fragments(payload: Any) -> None:
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    forbidden_fragments = [
        "<trkpt",
        "\"coordinates\"",
        "catographydata",
        "PdrSample",
        ".gpx",
        ".grd",
        ".hdr",
        ".jpg",
        ".jpeg",
        ".tif",
        ".tiff",
        "incident_samples",
        "raw_samples",
    ]
    for fragment in forbidden_fragments:
        if fragment in serialized:
            raise ValueError(f"departure bundle contains forbidden raw payload fragment: {fragment}")
