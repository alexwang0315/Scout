from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


DEFAULT_CHILAI_PROJECT_REF = (
    "tests/fixtures/pretrip/projects/chilai_nanhua_day1/project.json"
)


class StrictHandoffModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class HandoffRef(StrictHandoffModel):
    ref_key: str
    ref: str
    artifact_kind: str
    sha256: str
    exists: Literal[True] = True
    status: str | None = None
    summary: dict[str, Any] = Field(default_factory=dict)


class HandoffPackageVersion(StrictHandoffModel):
    package_id: str
    project_id: str
    version: str
    status: Literal["reviewed"]
    human_review_count: int = Field(ge=0)
    reviewed_package_is_not_departure_approval: Literal[True] = True
    departure_approval_granted: Literal[False] = False
    departure_gate_required_before_runtime: Literal[True] = True
    package_ref: HandoffRef
    reviewed_package_ref: HandoffRef


class HandoffRouteSource(StrictHandoffModel):
    artifact_id: str
    kind: str
    sha256: str
    media_type: str | None = None
    size_bytes: int | None = Field(default=None, ge=0)
    source_ref: str | None = None


class HandoffBoundary(StrictHandoffModel):
    candidate_metadata_only: Literal[True] = True
    reviewed_package_is_not_departure_approval: Literal[True] = True
    departure_approval_granted: Literal[False] = False
    departure_gate_required_before_runtime: Literal[True] = True
    runtime_handoff_operator_trigger_required: Literal[True] = True
    phase1_runtime_mutation_allowed: Literal[False] = False
    safety_api_calls_allowed: Literal[False] = False
    bridge_mutation_allowed: Literal[False] = False
    final_runtime_write_allowed: Literal[False] = False
    live_runtime_read_allowed: Literal[False] = False
    incident_package_imported: Literal[False] = False
    phase2_writeback_allowed: Literal[False] = False
    external_api_calls_made: Literal[False] = False
    raw_payloads_embedded: Literal[False] = False
    notes: list[str] = Field(default_factory=list)


class HandoffCounts(StrictHandoffModel):
    readiness_ref_count: int = Field(ge=0)
    route_ref_count: int = Field(ge=0)
    route_source_count: int = Field(ge=0)
    human_review_count: int = Field(ge=0)
    runtime_write_count: Literal[0] = 0
    safety_call_count: Literal[0] = 0
    bridge_mutation_count: Literal[0] = 0


class PreTripRuntimeHandoffMetadata(StrictHandoffModel):
    manifest_id: str
    artifact_kind: Literal["pretrip_runtime_handoff_metadata"] = (
        "pretrip_runtime_handoff_metadata"
    )
    project_id: str
    status: Literal["candidate_metadata_only"] = "candidate_metadata_only"
    plan_version_id: str
    package: HandoffPackageVersion
    reviewed_mission_graph_ref: HandoffRef
    readiness_refs: list[HandoffRef] = Field(default_factory=list)
    route_refs: list[HandoffRef] = Field(default_factory=list)
    route_source_refs: list[HandoffRouteSource] = Field(default_factory=list)
    boundary: HandoffBoundary = Field(default_factory=HandoffBoundary)
    counts: HandoffCounts
    integration_notes: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def enforce_candidate_metadata_boundary(self) -> "PreTripRuntimeHandoffMetadata":
        if self.status != "candidate_metadata_only":
            raise ValueError("runtime handoff metadata must stay candidate-only")
        _assert_no_runtime_or_raw_payload_fragments(self.model_dump(mode="json"))
        return self

    def to_json(self) -> str:
        return json.dumps(
            self.model_dump(mode="json"),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        ) + "\n"


def build_chilai_runtime_handoff_metadata(
    project_root: Path | str,
) -> PreTripRuntimeHandoffMetadata:
    project_path = _resolve_chilai_project_path(Path(project_root))
    fixture_root = project_path.parent
    project = _load_json(project_path)

    package_ref = _required_ref(
        fixture_root,
        project,
        ref_key="package_ref",
        artifact_kind="pretrip_package",
    )
    reviewed_package_ref = _required_ref(
        fixture_root,
        project,
        ref_key="reviewed_package_ref",
        artifact_kind="reviewed_pretrip_package",
    )
    reviewed_package = _load_json(fixture_root / reviewed_package_ref.ref)
    human_review_count = _human_review_count(fixture_root, project)

    readiness_refs = [
        _required_ref(
            fixture_root,
            project,
            ref_key="readiness_report_ref",
            artifact_kind="readiness_report",
        ),
        _required_ref(
            fixture_root,
            project,
            ref_key="plan_validation_candidates_ref",
            artifact_kind="plan_validation_candidates",
        ),
        _required_ref(
            fixture_root,
            project,
            ref_key="poi_readiness_candidates_ref",
            artifact_kind="poi_readiness_candidates",
        ),
    ]
    route_refs = [
        _required_ref(
            fixture_root,
            project,
            ref_key="route_summary_ref",
            artifact_kind="route_summary",
        ),
        _required_ref(
            fixture_root,
            project,
            ref_key="route_comparison_ref",
            artifact_kind="route_comparison",
        ),
        _required_ref(
            fixture_root,
            project,
            ref_key="planning_references_ref",
            artifact_kind="planning_references",
        ),
        _required_ref(
            fixture_root,
            project,
            ref_key="route_guide_timing_ref",
            artifact_kind="route_guide_timing_candidates",
        ),
    ]
    reviewed_mission_graph_ref = _required_ref(
        fixture_root,
        project,
        ref_key="compiled_mission_graph_reviewed_ref",
        artifact_kind="compiled_mission_graph_reviewed",
    )

    route_sources = [
        _route_source_ref(source)
        for source in reviewed_package.get("source_artifacts", [])
        if source.get("kind") in {"gpx", "geojson", "route", "map"}
    ]

    return PreTripRuntimeHandoffMetadata(
        manifest_id="runtime_handoff_metadata.chilai_nanhua_day1.v0",
        project_id=project["project_id"],
        plan_version_id=f"{reviewed_package['package_id']}:{reviewed_package['version']}",
        package=HandoffPackageVersion(
            package_id=reviewed_package["package_id"],
            project_id=reviewed_package["project_id"],
            version=reviewed_package["version"],
            status=reviewed_package["status"],
            human_review_count=human_review_count,
            package_ref=package_ref,
            reviewed_package_ref=reviewed_package_ref,
        ),
        reviewed_mission_graph_ref=reviewed_mission_graph_ref,
        readiness_refs=readiness_refs,
        route_refs=route_refs,
        route_source_refs=route_sources,
        boundary=HandoffBoundary(
            notes=[
                "Candidate metadata handoff only; no Phase 1 runtime state is mutated.",
                "Reviewed package metadata is not departure approval; the departure gate remains required.",
                "No safety endpoint is called and no Phase 3 bridge behavior is changed.",
                "No final runtime manifest or MissionGraph write is performed by this builder.",
            ],
        ),
        counts=HandoffCounts(
            readiness_ref_count=len(readiness_refs),
            route_ref_count=len(route_refs),
            route_source_count=len(route_sources),
            human_review_count=human_review_count,
        ),
        integration_notes=[
            "Main integration can later register this as a project artifact and release-check input.",
            "This slice intentionally leaves shared generators and release gates unchanged.",
        ],
    )


def load_runtime_handoff_metadata(path: Path | str) -> PreTripRuntimeHandoffMetadata:
    return PreTripRuntimeHandoffMetadata.model_validate_json(
        Path(path).read_text(encoding="utf-8")
    )


def _required_ref(
    fixture_root: Path,
    project: dict[str, Any],
    *,
    ref_key: str,
    artifact_kind: str,
) -> HandoffRef:
    ref = project.get(ref_key)
    if not ref:
        raise ValueError(f"missing runtime handoff metadata ref: {ref_key}")

    path = fixture_root / ref
    if not path.exists():
        raise ValueError(f"runtime handoff metadata ref does not exist: {ref_key}")

    payload = _load_json(path)
    return HandoffRef(
        ref_key=ref_key,
        ref=ref,
        artifact_kind=artifact_kind,
        sha256=_sha256_file(path),
        status=payload.get("status") if isinstance(payload, dict) else None,
        summary=_summary_for_artifact(artifact_kind, payload),
    )


def _summary_for_artifact(artifact_kind: str, payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {"item_count": len(payload)} if isinstance(payload, list) else {}

    if artifact_kind in {"pretrip_package", "reviewed_pretrip_package"}:
        metadata = payload.get("metadata") or {}
        boundary = payload.get("boundary") or {}
        return {
            "package_id": payload.get("package_id"),
            "version": payload.get("version"),
            "status": payload.get("status"),
            "source_artifact_count": len(payload.get("source_artifacts", [])),
            "checkpoint_candidate_count": len(payload.get("checkpoint_candidates", [])),
            "segment_candidate_count": len(payload.get("segment_candidates", [])),
            "human_review_count": metadata.get("human_review_count"),
            "reviewed_package_is_not_departure_approval": (
                metadata.get("reviewed_package_is_not_departure_approval")
                if metadata.get("reviewed_package_is_not_departure_approval") is not None
                else boundary.get("reviewed_package_is_not_departure_approval")
            ),
            "departure_approval_granted": (
                metadata.get("departure_approval_granted")
                if metadata.get("departure_approval_granted") is not None
                else boundary.get("departure_approval_granted")
            ),
        }

    if artifact_kind == "compiled_mission_graph_reviewed":
        return {
            "mission_id": payload.get("mission_id"),
            "name": payload.get("name"),
            "checkpoint_count": len(payload.get("checkpoints", [])),
            "segment_count": len(payload.get("segments", [])),
            "diversion_point_count": len(payload.get("diversion_points", [])),
            "route_source": _sanitize_source_ref(payload.get("route_source")),
        }

    if artifact_kind == "readiness_report":
        return {
            "status": payload.get("status"),
            "finding_count": len(payload.get("findings", [])),
        }

    if artifact_kind == "plan_validation_candidates":
        return {
            "status": payload.get("status"),
            "hard_readiness_status": payload.get("hard_readiness_status"),
            "hard_readiness_mutation_allowed": payload.get(
                "hard_readiness_mutation_allowed"
            ),
            "finding_count": len(payload.get("findings", [])),
        }

    if artifact_kind == "poi_readiness_candidates":
        counts = payload.get("counts", {})
        return {
            "status": payload.get("status"),
            "finding_candidate_count": counts.get("finding_candidate_count"),
            "blocker_candidate_count": counts.get("blocker_candidate_count"),
        }

    if artifact_kind == "route_summary":
        return {
            "artifact_id": _sanitize_source_ref(payload.get("artifact_id")),
            "route_name": payload.get("route_name"),
            "point_count": payload.get("point_count"),
            "distance_m": payload.get("distance_m"),
        }

    if artifact_kind == "route_comparison":
        return {
            "comparison_id": payload.get("comparison_id"),
            "classification": payload.get("classification"),
            "distance_delta_m": payload.get("distance_delta_m"),
            "point_count_delta": payload.get("point_count_delta"),
        }

    if artifact_kind == "planning_references":
        return {"reference_count": len(payload) if isinstance(payload, list) else 0}

    if artifact_kind == "route_guide_timing_candidates":
        return {"candidate_count": len(payload) if isinstance(payload, list) else 0}

    return {}


def _route_source_ref(source: dict[str, Any]) -> HandoffRouteSource:
    provenance = source.get("provenance", {})
    return HandoffRouteSource(
        artifact_id=_sanitize_source_ref(source["artifact_id"]),
        kind=source["kind"],
        sha256=source["sha256"],
        media_type=source.get("media_type"),
        size_bytes=source.get("size_bytes"),
        source_ref=_sanitize_source_ref(provenance.get("source_ref")),
    )


def _human_review_count(fixture_root: Path, project: dict[str, Any]) -> int:
    ref = project.get("human_reviews_ref")
    if not ref:
        return 0
    path = fixture_root / ref
    if not path.exists():
        return 0
    payload = _load_json(path)
    if not isinstance(payload, dict):
        return 0
    return len(payload.get("reviews", []))


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


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sanitize_source_ref(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    if ".gpx" in value.lower():
        return "artifact:gpx:chilai_nanhua_day1"
    return value.replace("artifact.gpx.", "artifact:gpx:").replace(
        "artifact.photo.",
        "artifact:photo:",
    )


def _assert_no_runtime_or_raw_payload_fragments(payload: Any) -> None:
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    forbidden_fragments = (
        "/safety",
        "Phase1IncidentBridge",
        "SCOUT_PHASE2_INCIDENT_BRIDGE",
        "<trkpt",
        '"coordinates"',
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
    )
    for fragment in forbidden_fragments:
        if fragment in serialized:
            raise ValueError(f"forbidden runtime/raw payload fragment: {fragment}")
