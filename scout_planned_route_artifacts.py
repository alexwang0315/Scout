"""Project-local immutable Planned bundles and explicit planning review.

The original Golden files, accepted mission baseline and runtime authority are
never modified here. A reviewed Planned bundle is still a planning candidate.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
from typing import Any, Literal
import uuid
import zipfile

from pydantic import Field, model_validator

from scout_planned_route_models import PlannedModel, PlannedRouteConflict, PlannedRouteRequest


STORE_REF = "reviews/planned_routes"
VERSION_PATTERN = re.compile(r"^plan\.[a-f0-9]{16,64}$")
SHA_PATTERN = r"^[a-f0-9]{64}$"
REVIEW_DIMENSIONS = ("sources", "geometry", "timing", "uncertainty")
AUTHORITY = {"candidate_only": True, "runtime_safety_truth": False,
             "departure_approval_granted": False, "recorded_track": False}


class PlannedSaveRequest(PlannedModel):
    request: PlannedRouteRequest
    expected_preview_sha256: str = Field(pattern=SHA_PATTERN)
    idempotency_key: str = Field(min_length=1, max_length=200)
    explicit_confirmation: Literal[True]


class PlannedReviewRequest(PlannedModel):
    version_id: str = Field(pattern=VERSION_PATTERN.pattern)
    expected_manifest_sha256: str = Field(pattern=SHA_PATTERN)
    reviewer_alias: str = Field(min_length=1, max_length=120)
    accepted_dimensions: list[Literal["sources", "geometry", "timing", "uncertainty"]]
    acknowledged_issue_ids: list[str] = Field(default_factory=list)
    idempotency_key: str = Field(min_length=1, max_length=200)
    explicit_confirmation: Literal[True]

    @model_validator(mode="after")
    def all_dimensions(self):
        if sorted(self.accepted_dimensions) != sorted(REVIEW_DIMENSIONS):
            raise ValueError("Review each of sources, geometry, timing and uncertainty once.")
        if len(set(self.acknowledged_issue_ids)) != len(self.acknowledged_issue_ids):
            raise ValueError("Acknowledged issue IDs must be unique.")
        return self


class PlannedAnalysisSelectionRequest(PlannedModel):
    subject_kind: Literal["golden_gpx", "planned_gpx"]
    version_id: str | None = Field(default=None, pattern=VERSION_PATTERN.pattern)
    expected_manifest_sha256: str | None = Field(default=None, pattern=SHA_PATTERN)
    expected_selection_sha256: str | None = Field(default=None, pattern=SHA_PATTERN)
    idempotency_key: str = Field(min_length=1, max_length=200)
    explicit_confirmation: Literal[True]

    @model_validator(mode="after")
    def planned_binding(self):
        if self.subject_kind == "planned_gpx":
            if not self.version_id or not self.expected_manifest_sha256:
                raise ValueError("Planned selection requires a version and manifest hash.")
        elif self.version_id is not None or self.expected_manifest_sha256 is not None:
            raise ValueError("Golden selection must not carry a Planned version.")
        return self


class PlannedTrailBBox(PlannedModel):
    south: float = Field(ge=-90, le=90)
    west: float = Field(ge=-180, le=180)
    north: float = Field(ge=-90, le=90)
    east: float = Field(ge=-180, le=180)

    @model_validator(mode="after")
    def ordered(self):
        if self.south >= self.north or self.west >= self.east:
            raise ValueError("Use a non-empty WGS84 area with ordered bounds.")
        return self


class PlannedTrailSourceRequest(PlannedModel):
    bbox: PlannedTrailBBox
    idempotency_key: str = Field(min_length=1, max_length=200)
    explicit_confirmation: Literal[True]


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"),
                      allow_nan=False).encode("utf-8")


def _sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _digest(value: Any) -> str:
    return _sha(canonical_bytes(value))


def _signed(value: dict, field: str) -> dict:
    return {**value, field: _digest(value)}


def _verify_signed(value: dict, field: str) -> None:
    if value.get(field) != _digest({k: v for k, v in value.items() if k != field}):
        raise PlannedRouteConflict("planned_artifact_hash_mismatch", "Saved planning evidence changed; reopen a valid version.")


def _assert_authority(value: dict) -> None:
    if any(value.get(key) is not expected for key, expected in AUTHORITY.items()):
        raise PlannedRouteConflict("planned_authority_mismatch", "Planned evidence must remain a non-operational planning candidate.")


def _safe_path(root: Path, ref: str) -> Path:
    relative = PurePosixPath(ref)
    if not ref or relative.is_absolute() or ".." in relative.parts or "\\" in ref:
        raise PlannedRouteConflict("invalid_planned_ref", "Use a project-relative planning artifact path.")
    target = root.joinpath(*relative.parts)
    for component in (target, *target.parents):
        if component == root:
            break
        if component.is_symlink():
            raise PlannedRouteConflict("invalid_planned_ref", "Planning artifact paths may not follow symlinks.")
    if root not in target.resolve().parents:
        raise PlannedRouteConflict("invalid_planned_ref", "Planning artifact is outside the selected project.")
    return target


def _read_bytes(root: Path, ref: str) -> bytes:
    path = _safe_path(root, ref)
    try:
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        with os.fdopen(fd, "rb") as stream:
            return stream.read()
    except OSError as exc:
        raise PlannedRouteConflict("planned_artifact_missing", f"Planning artifact is unavailable: {ref}") from exc


def _read_json(root: Path, ref: str) -> dict:
    content = _read_bytes(root, ref)
    try:
        value = json.loads(content)
    except (ValueError, UnicodeError) as exc:
        raise PlannedRouteConflict("invalid_planned_artifact", f"Invalid planning artifact: {ref}") from exc
    if not isinstance(value, dict):
        raise PlannedRouteConflict("invalid_planned_artifact", f"Expected an object in {ref}.")
    return value


def _project(root: Path) -> tuple[Path, str]:
    root = Path(root).resolve()
    project = _read_json(root, "project.json")
    project_id = project.get("project_id") or root.name
    if not isinstance(project_id, str) or project_id != root.name:
        raise PlannedRouteConflict("invalid_planned_project", "The workspace project identity does not match its directory.")
    return root, project_id


def _version_ref(version_id: str) -> str:
    if not VERSION_PATTERN.fullmatch(version_id):
        raise PlannedRouteConflict("invalid_planned_version", "Invalid Planned version id.")
    return f"{STORE_REF}/versions/{version_id}"


def _fsync_directory(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _write_new(path: Path, data: bytes) -> None:
    with path.open("xb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())


def _atomic_json(root: Path, ref: str, value: dict) -> None:
    path = _safe_path(root, ref)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.parent / f".{path.name}.{uuid.uuid4().hex}.pending"
    _write_new(temporary, canonical_bytes(value))
    # An interrupted write remains a hidden receipt, never an active selection.
    os.replace(temporary, path)
    _fsync_directory(path.parent)


@contextmanager
def _writer(root: Path):
    directory = _safe_path(root, STORE_REF)
    directory.mkdir(parents=True, exist_ok=True)
    lock_path = _safe_path(root, f"{STORE_REF}/.write.lock")
    fd = os.open(lock_path, os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0), 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def required_issue_ids(preview: dict) -> list[str]:
    """Stable acknowledgments include unlocated/unknown timing evidence."""
    values = list(preview.get("issues") or [])
    itinerary = preview.get("itinerary") or {}
    values += list(itinerary.get("unknowns") or [])
    values += list(itinerary.get("conflicts") or [])
    result = []
    for item in values:
        explicit = item.get("issue_id") or item.get("id") if isinstance(item, dict) else None
        issue_id = str(explicit) if explicit else "issue." + _digest(item)[:20]
        if issue_id not in result:
            result.append(issue_id)
    return result


def preview_for_review(preview: dict) -> dict:
    return {**preview, "review_requirements": {
        "accepted_dimensions": list(REVIEW_DIMENSIONS),
        "required_issue_ids": required_issue_ids(preview),
        "review_scope": "planning_candidate_only", "runtime_authorization": False,
    }}


def planned_day_bindings(preview: dict) -> list[dict]:
    """Map days to the new ordered CP/segment axis, including repeat visits."""
    result = []
    for index, day in enumerate((preview.get("itinerary") or {}).get("days", []), 1):
        start, end = day.get("start_point_index"), day.get("end_point_index")
        if isinstance(start, int) and isinstance(end, int):
            checkpoints = [cp.get("candidate_id") or cp.get("checkpoint_id") for cp in preview.get("checkpoints", [])
                           if isinstance(cp.get("point_index"), int) and start <= cp["point_index"] <= end]
            segments = [segment["segment_id"] for segment in preview.get("segments", [])
                        if isinstance(segment.get("start_point_index"), int)
                        and isinstance(segment.get("end_point_index"), int)
                        and segment["start_point_index"] < end and segment["end_point_index"] > start]
        else:
            checkpoints, segments = day.get("checkpoint_ids", []), day.get("segment_ids", [])
        result.append({"mission_day_id": day.get("mission_day_id") or day.get("day_id") or f"D{index}",
                       "start_point_index": start, "end_point_index": end,
                       "checkpoint_ids": [item for item in checkpoints if item], "segment_ids": segments})
    return result


def _compile(root: Path, request: PlannedRouteRequest) -> dict:
    from scout_planned_route import compile_planned_route
    result = compile_planned_route(root, request)
    if not isinstance(result, dict):
        raise PlannedRouteConflict("invalid_planned_preview", "The route compiler returned no valid preview.")
    if result.get("candidate_only") is not True or result.get("runtime_safety_truth") is not False:
        raise PlannedRouteConflict("planned_authority_mismatch", "Route compiler output cannot grant runtime authority.")
    if result.get("request") != request.model_dump(mode="json"):
        raise PlannedRouteConflict("planned_request_binding_mismatch", "Compiled intent differs from the requested intent.")
    _verify_signed(result, "preview_sha256")
    return result


def _source_status(root: Path, hashes: dict) -> dict:
    if not isinstance(hashes, dict) or not hashes:
        return {"status": "stale", "changed_refs": [], "reason": "source_hashes_missing"}
    changed = []
    for ref, expected in hashes.items():
        try:
            if not isinstance(ref, str) or not isinstance(expected, str) or _sha(_read_bytes(root, ref)) != expected:
                changed.append(str(ref))
        except PlannedRouteConflict:
            changed.append(str(ref))
    return {"status": "current" if not changed else "stale", "changed_refs": changed}


def _assert_sources(root: Path, hashes: dict) -> None:
    status = _source_status(root, hashes)
    if status["status"] != "current":
        raise PlannedRouteConflict("planned_sources_stale", "Planning sources changed or disappeared; generate a new preview.")


def _mission_candidate(preview: dict, version_id: str) -> dict:
    # Reuse the existing typed candidate representation, with an explicit
    # Planned graph handoff. It is not registered in the Golden accept chain.
    from scout_contextual_permission_workbench import MissionBaselineDraft
    itinerary = preview.get("itinerary") or {}
    day_rows = []
    bindings = planned_day_bindings(preview)
    for index, day in enumerate(itinerary.get("days") or [], 1):
        day_rows.append({
            "mission_day_id": day.get("mission_day_id") or day.get("day_id") or f"D{index}",
            "source_text": preview["request"].get("human_text", ""),
            "resolved_targets": bindings[index - 1]["checkpoint_ids"],
            "unresolved_names": [], "segment_ids": bindings[index - 1]["segment_ids"],
            "review_summary": "Planned geometry and estimated timetable; original Golden mission graph is not activated.",
        })
    return MissionBaselineDraft.model_validate({
        "artifact_kind": "mission_baseline_candidate", "schema_version": "missionBaselineCandidate.v1",
        "draft_id": version_id, "source_mode": "human_text", "source_sha256": preview["preview_sha256"],
        "source_text": preview["request"].get("human_text", ""),
        "source_refs": sorted(preview["source_hashes"]), "source_hashes": preview["source_hashes"],
        "route_axis_validation": {"planned_axis": "pass" if preview.get("route_axis") else "blocked",
                                  "golden_graph_activation": "blocked"},
        "days": day_rows, "validation_state": "needs_review",
        "unresolved_gaps": ["planned_route_graph_requires_its_own_analysis"],
        "assumptions": ["All timetable values describe a plan, not a recorded trip."],
        **{key: value for key, value in AUTHORITY.items() if key != "recorded_track"},
    }).model_dump(mode="json")


def _load_version(root: Path, version_id: str, expected: str | None = None) -> tuple[dict, dict]:
    ref = _version_ref(version_id)
    manifest = _read_json(root, ref + "/manifest.json")
    _verify_signed(manifest, "manifest_sha256")
    _assert_authority(manifest)
    _, project_id = _project(root)
    if (manifest.get("version_id") != version_id or manifest.get("project_id") != project_id
            or version_id != "plan." + str(manifest.get("command_sha256", ""))[:24]
            or (expected is not None and manifest.get("manifest_sha256") != expected)):
        raise PlannedRouteConflict("planned_version_binding_mismatch", "The version does not match this project or expected manifest.")
    required_files = {"planned.gpx", "itinerary.json", "route_axis.json", "checkpoints.json", "segments.json",
                      "route.geojson", "request.json", "preview.json", "mission_baseline_candidate.json"}
    files = manifest.get("files")
    if not isinstance(files, dict) or set(files) != required_files:
        raise PlannedRouteConflict("invalid_planned_manifest", "The complete GPX, route axis and itinerary bundle is required.")
    content_map = {}
    for filename, binding in files.items():
        content = _read_bytes(root, f"{ref}/{filename}")
        if not isinstance(binding, dict) or _sha(content) != binding.get("sha256") or len(content) != binding.get("bytes"):
            raise PlannedRouteConflict("planned_bundle_hash_mismatch", f"Saved Planned output changed: {filename}")
        content_map[filename] = content
    try:
        preview = json.loads(content_map["preview.json"])
    except (ValueError, UnicodeError) as exc:
        raise PlannedRouteConflict("invalid_planned_artifact", "Saved Planned preview is not valid JSON.") from exc
    if not isinstance(preview, dict):
        raise PlannedRouteConflict("invalid_planned_artifact", "Saved Planned preview must be an object.")
    _verify_signed(preview, "preview_sha256")
    if (preview.get("project_id") != project_id or preview.get("preview_sha256") != manifest.get("preview_sha256")
            or preview.get("geometry_sha256") != manifest.get("geometry_sha256")
            or preview.get("itinerary_sha256") != manifest.get("itinerary_sha256")
            or preview.get("source_hashes") != manifest.get("source_hashes")
            or preview.get("candidate_only") is not True or preview.get("runtime_safety_truth") is not False):
        raise PlannedRouteConflict("planned_bundle_binding_mismatch", "Saved route, itinerary and provenance do not identify one Planned version.")
    expected_documents = {
        "planned.gpx": str(preview.get("planned_gpx", "")).encode("utf-8"),
        "itinerary.json": canonical_bytes(preview.get("itinerary")),
        "route_axis.json": canonical_bytes(preview.get("route_axis")),
        "route.geojson": canonical_bytes(preview.get("route_geojson")),
        "request.json": canonical_bytes(preview.get("request")),
        "checkpoints.json": canonical_bytes({"checkpoints": preview.get("checkpoints", []), **AUTHORITY}),
        "segments.json": canonical_bytes({"segments": preview.get("segments", []), **AUTHORITY}),
        "mission_baseline_candidate.json": canonical_bytes(_mission_candidate(preview, version_id)),
    }
    if any(content_map[name] != expected for name, expected in expected_documents.items()):
        raise PlannedRouteConflict("planned_bundle_binding_mismatch", "Bundle files do not reproduce the same preview geometry and timetable.")
    return manifest, preview


def _version_manifests(root: Path) -> list[dict]:
    directory = _safe_path(root, f"{STORE_REF}/versions")
    if not directory.exists():
        return []
    result = []
    for path in sorted(directory.iterdir()):
        if path.name.startswith("."):
            continue
        if not path.is_dir() or not VERSION_PATTERN.fullmatch(path.name):
            raise PlannedRouteConflict("invalid_planned_version", "Unexpected artifact in the Planned version catalog.")
        manifest, _ = _load_version(root, path.name)
        result.append(manifest)
    return result


def _head(manifests: list[dict]) -> str | None:
    if not manifests:
        return None
    by_id = {item["version_id"]: item for item in manifests}
    parents = {item.get("parent_version_id") for item in manifests}
    if len(by_id) != len(manifests) or any(parent is not None and parent not in by_id for parent in parents):
        raise PlannedRouteConflict("planned_version_chain_conflict", "Planned version history has a missing parent.")
    heads = [item["version_id"] for item in manifests if item["version_id"] not in parents]
    if len(heads) != 1:
        raise PlannedRouteConflict("planned_version_chain_conflict", "Planned version history has conflicting heads.")
    visited = set()
    cursor = heads[0]
    while cursor is not None and cursor not in visited:
        visited.add(cursor)
        cursor = by_id[cursor].get("parent_version_id")
    if cursor is not None or len(visited) != len(manifests):
        raise PlannedRouteConflict("planned_version_chain_conflict", "Planned version history is not one complete revision chain.")
    return heads[0]


def _save_receipt(manifest: dict, *, replayed: bool) -> dict:
    return {key: manifest.get(key) for key in ("project_id", "version_id", "parent_version_id", "manifest_sha256",
                "preview_sha256", "geometry_sha256", "itinerary_sha256", "status", "created_at")} | {
        "manifest_ref": f"{_version_ref(manifest['version_id'])}/manifest.json",
        "review_status": "not_reviewed", "replayed": replayed, "writes_performed": not replayed,
        **AUTHORITY,
    }


def save_planned_version(project_root: Path, request: PlannedSaveRequest) -> dict:
    root, project_id = _project(project_root)
    command = request.model_dump(mode="json")
    command_sha = _digest(command)
    key_sha = _digest(request.idempotency_key)
    version_id = "plan." + command_sha[:24]
    with _writer(root):
        manifests = _version_manifests(root)
        for previous in manifests:
            if previous.get("idempotency_key_sha256") == key_sha:
                if previous.get("command_sha256") != command_sha:
                    raise PlannedRouteConflict("planned_idempotency_conflict", "This Save key already identifies a different plan.")
                return _save_receipt(previous, replayed=True)
        if request.request.parent_version_id != _head(manifests):
            raise PlannedRouteConflict("planned_parent_version_conflict", "A newer Planned version exists; reopen it before saving a revision.")
        preview = _compile(root, request.request)
        if preview.get("project_id") != project_id or preview.get("preview_sha256") != request.expected_preview_sha256:
            raise PlannedRouteConflict("planned_preview_stale", "The preview changed; inspect the new geometry and timetable before Save.")
        if preview.get("status") == "blocked":
            raise PlannedRouteConflict("planned_preview_blocked", "Resolve the blocking geometry or timetable conflicts before Save.")
        _assert_sources(root, preview.get("source_hashes"))
        documents = {
            "planned.gpx": str(preview["planned_gpx"]).encode("utf-8"),
            "itinerary.json": canonical_bytes(preview["itinerary"]),
            "route_axis.json": canonical_bytes(preview["route_axis"]),
            "checkpoints.json": canonical_bytes({"checkpoints": preview.get("checkpoints", []), **AUTHORITY}),
            "segments.json": canonical_bytes({"segments": preview.get("segments", []), **AUTHORITY}),
            "route.geojson": canonical_bytes(preview["route_geojson"]),
            "request.json": canonical_bytes(preview["request"]),
            "preview.json": canonical_bytes(preview),
            "mission_baseline_candidate.json": canonical_bytes(_mission_candidate(preview, version_id)),
        }
        manifest = _signed({
            "artifact_kind": "planned_route_candidate_bundle", "schema_version": "plannedRouteBundle.v1",
            "project_id": project_id, "version_id": version_id, "parent_version_id": request.request.parent_version_id,
            "created_at": datetime.now(timezone.utc).isoformat(), "command_sha256": command_sha,
            "idempotency_key_sha256": key_sha, "preview_sha256": preview["preview_sha256"],
            "geometry_sha256": preview["geometry_sha256"], "itinerary_sha256": preview["itinerary_sha256"],
            "source_snapshot_sha256": preview.get("source_snapshot_sha256"), "source_hashes": preview["source_hashes"],
            "status": preview["status"], "required_issue_ids": required_issue_ids(preview),
            "files": {name: {"sha256": _sha(content), "bytes": len(content)} for name, content in documents.items()},
            "review_scope": "planning_candidate_only", "time_role": "planned_estimate",
            "golden_baseline_mutated": False, **AUTHORITY,
        }, "manifest_sha256")
        directory = _safe_path(root, f"{STORE_REF}/versions")
        directory.mkdir(parents=True, exist_ok=True)
        stage = directory / f".{version_id}.{uuid.uuid4().hex}.pending"
        stage.mkdir(mode=0o700)
        for name, content in documents.items():
            _write_new(stage / name, content)
        _write_new(stage / "manifest.json", canonical_bytes(manifest))
        # Detect writes which raced compilation/staging before publication.
        _assert_sources(root, preview["source_hashes"])
        for name, binding in manifest["files"].items():
            if _sha((stage / name).read_bytes()) != binding["sha256"]:
                raise PlannedRouteConflict("planned_staging_hash_mismatch", "Planning output changed during Save; previous version is intact.")
        _fsync_directory(stage)
        target = _safe_path(root, _version_ref(version_id))
        if target.exists():
            raise PlannedRouteConflict("planned_version_exists", "The immutable Planned version already exists.")
        os.rename(stage, target)
        _fsync_directory(directory)
        return _save_receipt(manifest, replayed=False)


def _review_records(root: Path, version_id: str, manifest_sha: str) -> list[dict]:
    directory = _safe_path(root, f"{STORE_REF}/reviews/{version_id}")
    if not directory.exists():
        return []
    result = []
    for path in sorted(directory.glob("*.json")):
        record = _read_json(root, path.relative_to(root).as_posix())
        _verify_signed(record, "review_sha256")
        _assert_authority(record)
        if (record.get("version_id") != version_id or record.get("manifest_sha256") != manifest_sha
                or record.get("project_id") != _project(root)[1]
                or sorted(record.get("accepted_dimensions", [])) != sorted(REVIEW_DIMENSIONS)):
            raise PlannedRouteConflict("planned_review_binding_mismatch", "Planning review does not match the selected version.")
        result.append(record)
    return result


def _assert_compiler_replay(root: Path, manifest: dict, preview: dict) -> None:
    _assert_sources(root, manifest["source_hashes"])
    request = PlannedRouteRequest.model_validate(preview["request"])
    fresh = _compile(root, request)
    if fresh.get("preview_sha256") != manifest["preview_sha256"] or fresh != preview:
        raise PlannedRouteConflict("planned_compiler_replay_changed", "Source or compiler output changed; create and review a new Planned version.")


def review_planned_version(project_root: Path, request: PlannedReviewRequest) -> dict:
    root, project_id = _project(project_root)
    command_sha = _digest(request.model_dump(mode="json"))
    key_sha = _digest(request.idempotency_key)
    with _writer(root):
        manifest, preview = _load_version(root, request.version_id, request.expected_manifest_sha256)
        previous = _review_records(root, request.version_id, manifest["manifest_sha256"])
        # Idempotency keys are project/action scoped, including revisions.
        review_root = _safe_path(root, f"{STORE_REF}/reviews")
        if review_root.exists():
            for path in review_root.glob("*/*.json"):
                if path.parent.name == request.version_id:
                    continue
                record = _read_json(root, path.relative_to(root).as_posix())
                if record.get("idempotency_key_sha256") == key_sha:
                    _verify_signed(record, "review_sha256")
                    raise PlannedRouteConflict("planned_idempotency_conflict", "This review key already identifies a different Planned version.")
        for record in previous:
            if record.get("idempotency_key_sha256") == key_sha:
                if record.get("command_sha256") != command_sha:
                    raise PlannedRouteConflict("planned_idempotency_conflict", "This review key identifies different acceptance evidence.")
                return {**record, "replayed": True, "writes_performed": False}
        _assert_compiler_replay(root, manifest, preview)
        if manifest["status"] == "blocked":
            raise PlannedRouteConflict("planned_review_blocked", "Blocking geometry or timetable gaps cannot be accepted by acknowledgment.")
        if set(request.acknowledged_issue_ids) != set(manifest["required_issue_ids"]):
            raise PlannedRouteConflict("planned_review_acknowledgments_incomplete", "Review every current uncertainty; stale or additional acknowledgment IDs are not accepted.")
        review_id = "review." + command_sha[:24]
        ref = f"{STORE_REF}/reviews/{request.version_id}/{review_id}.json"
        record = _signed({
            "schema_version": "plannedRouteReview.v1", "project_id": project_id,
            "review_id": review_id, "review_ref": ref, "version_id": request.version_id,
            "manifest_sha256": manifest["manifest_sha256"], "preview_sha256": manifest["preview_sha256"],
            "geometry_sha256": manifest["geometry_sha256"], "itinerary_sha256": manifest["itinerary_sha256"],
            "source_snapshot_sha256": manifest["source_snapshot_sha256"],
            "reviewer_alias": request.reviewer_alias, "accepted_dimensions": list(request.accepted_dimensions),
            "acknowledged_issue_ids": list(request.acknowledged_issue_ids),
            "idempotency_key_sha256": key_sha, "command_sha256": command_sha,
            "created_at": datetime.now(timezone.utc).isoformat(), "status": "reviewed_planning_candidate",
            "review_scope": "planning_candidate_only", **AUTHORITY,
        }, "review_sha256")
        _atomic_json(root, ref, record)
        return {**record, "replayed": False, "writes_performed": True}


def get_analysis_selection(project_root: Path) -> dict:
    root, project_id = _project(project_root)
    ref = f"{STORE_REF}/analysis_selection.json"
    if not _safe_path(root, ref).exists():
        return {"project_id": project_id, "subject_kind": "golden_gpx", "version_id": None,
                "selection_sha256": None, "selection_status": "default", **AUTHORITY}
    value = _read_json(root, ref)
    _verify_signed(value, "selection_sha256")
    _assert_authority(value)
    if value.get("project_id") != project_id or value.get("subject_kind") not in {"golden_gpx", "planned_gpx"}:
        raise PlannedRouteConflict("planned_selection_binding_mismatch", "Analysis selection does not match this project.")
    return value


def select_analysis_subject(project_root: Path, request: PlannedAnalysisSelectionRequest) -> dict:
    root, project_id = _project(project_root)
    command_sha = _digest(request.model_dump(mode="json"))
    key_sha = _digest(request.idempotency_key)
    with _writer(root):
        previous = get_analysis_selection(root)
        history_ref = f"{STORE_REF}/selections/{key_sha}.json"
        if _safe_path(root, history_ref).exists():
            earlier = _read_json(root, history_ref)
            _verify_signed(earlier, "selection_sha256")
            if earlier.get("command_sha256") != command_sha:
                raise PlannedRouteConflict("planned_idempotency_conflict", "This selection key already identifies another analysis choice.")
            if previous.get("selection_sha256") == earlier["selection_sha256"]:
                return {**earlier, "replayed": True, "writes_performed": False}
            if previous.get("selection_sha256") != earlier.get("previous_selection_sha256"):
                raise PlannedRouteConflict("planned_selection_superseded", "This choice has been superseded; reload the current analysis selection.")
            # A crash after the immutable receipt but before pointer publication
            # is recoverable only while its predecessor is still current.
        else:
            earlier = None
        if request.expected_selection_sha256 != previous.get("selection_sha256"):
            raise PlannedRouteConflict("planned_selection_conflict", "Analysis selection changed; reload before switching versions.")
        manifest = review = None
        if request.subject_kind == "planned_gpx":
            manifest, preview = _load_version(root, request.version_id, request.expected_manifest_sha256)
            _assert_compiler_replay(root, manifest, preview)
            records = _review_records(root, request.version_id, manifest["manifest_sha256"])
            if not records:
                raise PlannedRouteConflict("planned_review_required", "Review sources, geometry, timing and uncertainty before selecting Planned.")
            review = records[-1]
        record = earlier or _signed({
            "schema_version": "plannedAnalysisSelection.v1", "project_id": project_id,
            "subject_kind": request.subject_kind, "version_id": request.version_id,
            "manifest_sha256": manifest["manifest_sha256"] if manifest else None,
            "review_ref": review["review_ref"] if review else None,
            "review_sha256": review["review_sha256"] if review else None,
            "previous_selection_sha256": request.expected_selection_sha256,
            "idempotency_key_sha256": key_sha, "command_sha256": command_sha,
            "created_at": datetime.now(timezone.utc).isoformat(), "selection_status": "selected",
            **AUTHORITY,
        }, "selection_sha256")
        if earlier is None:
            _atomic_json(root, history_ref, record)
        _atomic_json(root, f"{STORE_REF}/analysis_selection.json", record)
        return {**record, "replayed": earlier is not None, "writes_performed": True}


def get_planned_version(project_root: Path, version_id: str) -> dict:
    root, _ = _project(project_root)
    manifest, preview = _load_version(root, version_id)
    records = _review_records(root, version_id, manifest["manifest_sha256"])
    return {"manifest": manifest, "preview": preview_for_review(preview),
            "review": records[-1] if records else None,
            "source_status": _source_status(root, manifest["source_hashes"]),
            "analysis_selection": get_analysis_selection(root), **AUTHORITY}


def list_planned_versions(project_root: Path) -> dict:
    root, project_id = _project(project_root)
    manifests = _version_manifests(root)
    rows = []
    for manifest in manifests:
        records = _review_records(root, manifest["version_id"], manifest["manifest_sha256"])
        rows.append({key: manifest.get(key) for key in ("version_id", "manifest_sha256", "preview_sha256",
                    "status", "created_at", "parent_version_id", "geometry_sha256", "itinerary_sha256")} | {
            "review_status": "reviewed_planning_candidate" if records else "not_reviewed",
            "source_status": _source_status(root, manifest["source_hashes"])["status"],
        })
    return {"project_id": project_id, "versions": sorted(rows, key=lambda row: row["created_at"], reverse=True),
            "head_version_id": _head(manifests), "analysis_selection": get_analysis_selection(root), **AUTHORITY}


def selected_planned_bundle(project_root: Path) -> dict | None:
    """Read-only dependency admission; never silently substitute old Golden."""
    root, _ = _project(project_root)
    selection = get_analysis_selection(root)
    if selection["subject_kind"] == "golden_gpx":
        return None
    manifest, preview = _load_version(root, selection["version_id"], selection["manifest_sha256"])
    record = _read_json(root, selection["review_ref"])
    _verify_signed(record, "review_sha256")
    _assert_authority(record)
    if (record.get("review_sha256") != selection["review_sha256"]
            or record.get("version_id") != manifest["version_id"]
            or record.get("manifest_sha256") != manifest["manifest_sha256"]
            or record.get("project_id") != manifest["project_id"]
            or sorted(record.get("accepted_dimensions", [])) != sorted(REVIEW_DIMENSIONS)
            or set(record.get("acknowledged_issue_ids", [])) != set(manifest["required_issue_ids"])):
        raise PlannedRouteConflict("planned_review_binding_mismatch", "The selected Planned review no longer matches this version.")
    return {"selection": selection, "manifest": manifest, "preview": preview,
            "review": record, "source_status": _source_status(root, manifest["source_hashes"])}


def export_planned_version(project_root: Path, version_id: str, format: str) -> tuple[bytes, str, str]:
    root, _ = _project(project_root)
    manifest, _ = _load_version(root, version_id)
    ref = _version_ref(version_id)
    def verified_output(filename: str) -> bytes:
        content = _read_bytes(root, f"{ref}/{filename}")
        if _sha(content) != manifest["files"][filename]["sha256"]:
            raise PlannedRouteConflict("planned_export_changed", "Saved output changed during export; no mixed-version bundle is returned.")
        return content
    if format == "gpx":
        return verified_output("planned.gpx"), "application/gpx+xml", f"{version_id}.planned.gpx"
    if format == "manifest":
        return canonical_bytes(manifest), "application/json", f"{version_id}.manifest.json"
    if format != "bundle":
        raise PlannedRouteConflict("invalid_planned_export", "Export gpx, manifest or bundle.")
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for filename in sorted([*manifest["files"], "manifest.json"]):
            archive.writestr(filename, canonical_bytes(manifest) if filename == "manifest.json" else verified_output(filename))
    return output.getvalue(), "application/zip", f"{version_id}.planned-bundle.zip"


def acquire_planned_trail_sources(project_root: Path, request: PlannedTrailSourceRequest) -> dict:
    """Acquire a fixed-endpoint public map candidate and append its source binding.

    Publication is recoverable after the content-addressed files/receipt exist.
    Only the Planned source list in project.json changes; Golden refs stay put.
    """
    from scout_planned_route import load_planned_catalog
    from scout_planned_route_sources import fetch_trail_source_candidates

    root, project_id = _project(project_root)
    command_sha = _digest(request.model_dump(mode="json"))
    key_sha = _digest(request.idempotency_key)
    receipt_ref = f"{STORE_REF}/source_imports/{key_sha}.json"
    with _writer(root):
        replayed = _safe_path(root, receipt_ref).exists()
        if replayed:
            receipt = _read_json(root, receipt_ref)
            _verify_signed(receipt, "receipt_sha256")
            _assert_authority(receipt)
            if receipt.get("command_sha256") != command_sha or receipt.get("project_id") != project_id:
                raise PlannedRouteConflict("planned_idempotency_conflict", "This source-query key already identifies another area.")
        else:
            before_sha = _sha(_read_bytes(root, "project.json"))
            try:
                fetched = fetch_trail_source_candidates(request.bbox.model_dump(mode="json"))
            except PlannedRouteConflict:
                raise
            except (OSError, ValueError) as exc:
                raise PlannedRouteConflict("planned_source_fetch_unavailable", "The public trail query did not return usable evidence; retry the same request.") from exc
            if fetched.get("candidate_only") is not True or fetched.get("runtime_safety_truth") is not False:
                raise PlannedRouteConflict("planned_authority_mismatch", "Map evidence must remain candidate-only.")
            files, source_hashes = fetched.get("files"), fetched.get("source_hashes")
            if not isinstance(files, dict) or not files or set(files) != set(source_hashes or {}):
                raise PlannedRouteConflict("invalid_planned_source_bundle", "The map query returned no complete provenance bundle.")
            for ref, content in files.items():
                if (not isinstance(ref, str) or not re.fullmatch(r"normalized/map/planned-overpass/[a-f0-9]{64}/[A-Za-z0-9._-]+", ref)
                        or not isinstance(content, bytes) or _sha(content) != source_hashes[ref]):
                    raise PlannedRouteConflict("invalid_planned_source_bundle", "Map source paths or hashes failed verification.")
            directories = {str(PurePosixPath(ref).parent) for ref in files}
            if len(directories) != 1:
                raise PlannedRouteConflict("invalid_planned_source_bundle", "Raw and vector evidence must publish as one source bundle.")
            binding = fetched.get("project_binding") or {}
            if (binding.get("ref") not in source_hashes or binding.get("raw_ref") not in source_hashes
                    or binding.get("sha256") != source_hashes[binding["ref"]]
                    or binding.get("raw_sha256") != source_hashes[binding["raw_ref"]]):
                raise PlannedRouteConflict("invalid_planned_source_bundle", "Map source binding does not match the saved raw/vector evidence.")
            target = _safe_path(root, directories.pop())
            if target.exists():
                for ref in files:
                    if _sha(_read_bytes(root, ref)) != source_hashes[ref]:
                        raise PlannedRouteConflict("planned_source_immutable_conflict", "A content-addressed map source has changed.")
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                stage = target.parent / f".{target.name}.{uuid.uuid4().hex}.pending"
                stage.mkdir(mode=0o700)
                for ref, content in files.items():
                    _write_new(stage / PurePosixPath(ref).name, content)
                for ref, expected in source_hashes.items():
                    if _sha((stage / PurePosixPath(ref).name).read_bytes()) != expected:
                        raise PlannedRouteConflict("planned_source_immutable_conflict", "Map source changed during publication.")
                _fsync_directory(stage)
                os.rename(stage, target)
                _fsync_directory(target.parent)
            receipt = _signed({
                "schema_version": "plannedTrailSourceReceipt.v1", "project_id": project_id,
                "receipt_ref": receipt_ref, "command_sha256": command_sha, "idempotency_key_sha256": key_sha,
                "project_before_sha256": before_sha, "project_binding": binding, "source_hashes": source_hashes,
                "bbox_wgs84": request.bbox.model_dump(mode="json"), "query": fetched.get("query"),
                "created_at": datetime.now(timezone.utc).isoformat(), **AUTHORITY,
            }, "receipt_sha256")
            _atomic_json(root, receipt_ref, receipt)
        _assert_sources(root, receipt["source_hashes"])
        content = _read_bytes(root, "project.json")
        project = json.loads(content)
        bindings = project.get("planned_overpass_source_refs") or []
        if not isinstance(bindings, list):
            raise PlannedRouteConflict("invalid_planned_source_bindings", "Planned Overpass source bindings must be a list.")
        changed = receipt["project_binding"] not in bindings
        if changed:
            if _sha(content) != receipt["project_before_sha256"]:
                raise PlannedRouteConflict("planned_source_project_conflict", "The project changed during source acquisition; the fetched candidate is preserved for review.")
            project["planned_overpass_source_refs"] = [*bindings, receipt["project_binding"]]
            _atomic_json(root, "project.json", project)
        return {"status": "candidate_sources_saved", "project_id": project_id,
                "project_binding": receipt["project_binding"], "source_hashes": receipt["source_hashes"],
                "receipt_ref": receipt_ref, "receipt_sha256": receipt["receipt_sha256"],
                "catalog": load_planned_catalog(root), "replayed": replayed,
                "writes_performed": not replayed or changed, **AUTHORITY}
