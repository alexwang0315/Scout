"""Explicit map rebuilds and immutable human-review packets for Planned GPX."""
from __future__ import annotations

import fcntl
import hashlib
import json
import re
import uuid
from pathlib import Path
from typing import Any, Callable, Literal

from fastapi import APIRouter, HTTPException, Query, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator

from scout_planned_map_materialization import (
    PlannedRudyTraceRequest, RudyMapEvidence, _json_bytes, _project, _safe,
    inspect_map_materialization, materialize_map_sources, materialize_rudy_trace,
    read_materialization_catalog,
)
from scout_planned_route_sources import BOUNDARY, _Reader, load_map_route_sources

PACKET_SCHEMA = "plannedMapRegisteredReviewPacket.v1"
PACKET_CATALOG = "outputs/planned_map_sources/review_packets/catalog.json"


class MapCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PlannedMapRebuildCommand(MapCommand):
    source_kind: Literal["osm_pbf", "mapsforge_vector"] = "osm_pbf"
    source_ref: str
    expected_source_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    bbox_wgs84: dict[str, float] | None = None
    requested_by: str = Field(min_length=1, max_length=120)
    explicit_rebuild_confirmed: Literal[True]


class PlannedRudyDraftCommand(MapCommand):
    label: str = Field(min_length=1, max_length=240)
    geometry: dict[str, Any]
    map_evidence: list[RudyMapEvidence] = Field(min_length=1)
    created_by: str = Field(min_length=1, max_length=120)
    review_note: str = Field(min_length=1, max_length=4000)
    draft_creation_confirmed: Literal[True]


class PlannedMapHumanReviewCommand(MapCommand):
    expected_manifest_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    reviewer_name: str = Field(min_length=1, max_length=120)
    review_note: str = Field(min_length=1, max_length=4000)
    candidate_review_confirmed: Literal[True]
    source_geometry_confirmed: Literal[True]

    @field_validator("reviewer_name", "review_note")
    @classmethod
    def explicit_text(cls, value):
        if not value.strip():
            raise ValueError("An explicit reviewer name and review note are required")
        return value.strip()


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _packet_entries(root):
    path = _safe(root, PACKET_CATALOG, exists=False)
    if not path.exists():
        return []
    payload = json.loads(path.read_bytes())
    if payload.get("schema_version") != PACKET_SCHEMA or payload.get("project_id") != _project(root)["project_id"] or not isinstance(payload.get("entries"), list):
        raise ValueError("Review packet catalog identity is invalid")
    return payload["entries"]


def register_planned_map_review_packet(project_root: Path, *, packet: dict, source_hashes: dict[str, str],
                                       attachments: dict[str, bytes] | None = None) -> dict:
    """Bind an already prepared local packet; never records a human decision.

    Intended for deterministic preparation/CLI producers, not an HTTP upload or
    arbitrary-file browser. The server serves only this manifest's artifacts.
    """
    root = Path(project_root).resolve()
    project_id = _project(root)["project_id"]
    if packet.get("project_id") != project_id or packet.get("candidate_only") is not True or packet.get("runtime_safety_truth") is not False:
        raise ValueError("Review packet must match the candidate-only workspace")
    reader = _Reader(root)
    for ref, sha in source_hashes.items():
        reader.bind(ref, sha)
    files = {"packet.json": _json_bytes(packet), **(attachments or {})}
    if any(Path(name).name != name or name in ("manifest.json", "catalog.json") for name in files):
        raise ValueError("Review packet attachment names must be simple filenames")
    identity = {"schema_version": PACKET_SCHEMA, "project_id": project_id,
                "files": {name: _sha(raw) for name, raw in files.items()}, "source_hashes": source_hashes}
    packet_id = _sha(_json_bytes(identity))
    prefix = f"outputs/planned_map_sources/review_packets/{packet_id}"
    artifacts = {f"{prefix}/{name}": _sha(raw) for name, raw in files.items()}
    manifest = {**identity, "packet_id": packet_id, "packet_ref": f"{prefix}/packet.json",
                "artifacts": artifacts, "status": "pending_human_review", **BOUNDARY}
    manifest_ref = f"{prefix}/manifest.json"
    raw_manifest = _json_bytes(manifest)
    entry = {"packet_id": packet_id, "manifest_ref": manifest_ref, "manifest_sha256": _sha(raw_manifest)}
    catalog_path = _safe(root, PACKET_CATALOG, exists=False)
    lock_path = _safe(root, "outputs/planned_map_sources/review_packets/catalog.lock", exists=False)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+b") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        entries = _packet_entries(root)
        for ref, sha in source_hashes.items():
            reader.bind(ref, sha)
        outputs = {f"{prefix}/{name}": raw for name, raw in files.items()}
        outputs[manifest_ref] = raw_manifest
        for ref, raw in outputs.items():
            path = _safe(root, ref, exists=False)
            if path.exists() and path.read_bytes() != raw:
                raise ValueError("Immutable review packet collision")
            path.parent.mkdir(parents=True, exist_ok=True)
            if not path.exists():
                with path.open("xb") as stream:
                    stream.write(raw)
        if entry not in entries:
            entries.append(entry)
            temp = catalog_path.with_name(f"catalog.{uuid.uuid4().hex}.tmp")
            temp.write_bytes(_json_bytes({"schema_version": PACKET_SCHEMA, "project_id": project_id, "entries": entries, **BOUNDARY}))
            temp.replace(catalog_path)
    return {**entry, "packet_ref": manifest["packet_ref"], "status": "pending_human_review", **BOUNDARY}


def _inspect_packet(root, packet_id):
    entry = next((row for row in _packet_entries(root) if row.get("packet_id") == packet_id), None)
    if entry is None:
        raise ValueError("Review packet is not registered for this workspace")
    reader = _Reader(root)
    manifest = reader.read(entry["manifest_ref"], entry["manifest_sha256"])
    if (manifest.get("schema_version") != PACKET_SCHEMA or manifest.get("packet_id") != packet_id
            or manifest.get("project_id") != _project(root)["project_id"]
            or any(manifest.get(key) != value for key, value in BOUNDARY.items())):
        raise ValueError("Review packet manifest identity or candidate authority is invalid")
    for ref, sha in {**manifest["artifacts"], **manifest["source_hashes"]}.items():
        reader.bind(ref, sha)
    packet = reader.read(manifest["packet_ref"], manifest["artifacts"][manifest["packet_ref"]])
    return {**entry, "manifest": manifest, "packet": packet, "project_id": manifest["project_id"], **BOUNDARY}


def _packet_catalog(root):
    result = []
    for entry in _packet_entries(root):
        try:
            packet = _inspect_packet(root, entry["packet_id"])
            result.append({**entry, "status": "pending_human_review", "guidance_id": packet["packet"].get("guidance_id")})
        except (ValueError, OSError, KeyError, TypeError) as exc:
            result.append({**entry, "status": "stale_or_unavailable", "reason": str(exc)})
    return result


def create_planned_map_router(*, project_root_for: Callable[[str], Path]) -> APIRouter:
    """Mount below /admin; authentication remains with the owning workbench."""
    router = APIRouter(tags=["planned-map-candidate-review"])
    prefix = "/pretrip/projects/{project_id}/planned-map"

    def run(project_id, action):
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", project_id):
            raise HTTPException(422, detail={"code": "invalid_project_id", "message": "Invalid workspace identity"})
        try:
            root = project_root_for(project_id)
            if root is None or not Path(root).is_dir():
                raise HTTPException(404, detail={"code": "project_missing", "message": "Workspace is unavailable"})
            root = Path(root).resolve()
            if _project(root)["project_id"] != project_id:
                raise ValueError("Resolved workspace identity does not match the requested project")
            return action(root)
        except (ValueError, OSError, KeyError, TypeError) as exc:
            raise HTTPException(409, detail={"code": "planned_map_conflict", "message": str(exc)}) from exc

    def inspect(root, version_id):
        if not re.fullmatch(r"[a-f0-9]{64}", version_id):
            raise ValueError("Invalid immutable map version identity")
        return inspect_map_materialization(root, version_id)

    def artifact(root, inspected, ref, expected):
        if inspected["manifest_sha256"] != expected:
            raise ValueError("The review manifest has changed; reload the exact version")
        registered = inspected["manifest"]["artifacts"]
        if ref not in registered:
            raise ValueError("Requested artifact is not registered by this review manifest")
        path = _safe(root, ref)
        raw = path.read_bytes()
        if _sha(raw) != registered[ref]:
            raise ValueError("Registered review artifact changed while reading")
        types = {".png": "image/png", ".json": "application/json", ".geojson": "application/geo+json",
                 ".svg": "image/svg+xml", ".txt": "text/plain"}
        if path.suffix not in types:
            raise ValueError("This registered artifact type cannot be displayed")
        return Response(raw, media_type=types[path.suffix], headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": "default-src 'none'; img-src data:; style-src 'unsafe-inline'; sandbox"})

    @router.get(prefix + "/catalog")
    def catalog(project_id: str, response: Response):
        response.headers["Cache-Control"] = "no-store"
        def load(root):
            project = _project(root)
            candidates = []
            for key in ("osm_pbf_route_extract_ref", "osm_pbf_render_extract_ref"):
                ref = project.get(key)
                if not ref or any(item["source_ref"] == ref for item in candidates):
                    continue
                try:
                    raw = _safe(root, ref).read_bytes()
                    candidates.append({"source_kind": "osm_pbf", "source_ref": ref, "sha256": _sha(raw), "size_bytes": len(raw), "status": "available"})
                except (ValueError, OSError) as exc:
                    candidates.append({"source_ref": ref, "status": "unavailable", "reason": str(exc)})
            mapsforge = []
            ref = project.get("rudy_mapsforge_ref")
            if ref:
                try:
                    source = _safe(root, ref)
                    mapsforge.append({"source_kind": "mapsforge_vector", "source_ref": ref,
                        "sha256": _Reader(root).bind(ref), "size_bytes": source.stat().st_size, "status": "available"})
                except (ValueError, OSError) as exc:
                    mapsforge.append({"source_ref": ref, "status": "unavailable", "reason": str(exc)})
            mapped = load_map_route_sources(root, project)
            return {**mapped, "project_id": project_id, "pbf_sources": candidates, "mapsforge_sources": mapsforge, "review_packets": _packet_catalog(root),
                    "guidance": {"guidance_id": project.get("terrain_route_guidance_id"), "status": project.get("terrain_route_guidance_status"),
                                 "guided_execution_ready": project.get("terrain_route_guidance_guided_execution_ready") is True}, **BOUNDARY}
        return run(project_id, load)

    @router.get(prefix + "/versions")
    def versions(project_id: str, response: Response):
        response.headers["Cache-Control"] = "no-store"
        return run(project_id, lambda root: {"project_id": project_id, **read_materialization_catalog(root, project_id), **BOUNDARY})

    @router.get(prefix + "/versions/{version_id}")
    def version(project_id: str, version_id: str, response: Response):
        response.headers["Cache-Control"] = "no-store"
        return run(project_id, lambda root: inspect(root, version_id))

    @router.get(prefix + "/versions/{version_id}/artifact")
    def version_artifact(project_id: str, version_id: str, ref: str,
                         expected_manifest_sha256: str = Query(pattern=r"^[a-f0-9]{64}$")):
        return run(project_id, lambda root: artifact(root, inspect(root, version_id), ref, expected_manifest_sha256))

    @router.get(prefix + "/packets/{packet_id}")
    def packet(project_id: str, packet_id: str, response: Response):
        response.headers["Cache-Control"] = "no-store"
        return run(project_id, lambda root: _inspect_packet(root, packet_id))

    @router.get(prefix + "/packets/{packet_id}/artifact")
    def packet_artifact(project_id: str, packet_id: str, ref: str,
                        expected_manifest_sha256: str = Query(pattern=r"^[a-f0-9]{64}$")):
        return run(project_id, lambda root: artifact(root, _inspect_packet(root, packet_id), ref, expected_manifest_sha256))

    @router.post(prefix + "/rebuild", status_code=201)
    def rebuild(project_id: str, command: PlannedMapRebuildCommand):
        def build(root):
            project = _project(root)
            keys = ("rudy_mapsforge_ref",) if command.source_kind == "mapsforge_vector" else ("osm_pbf_route_extract_ref", "osm_pbf_render_extract_ref")
            allowed = {project.get(key) for key in keys}
            if command.source_ref not in allowed:
                raise ValueError("Rebuild requires a map source registered by the selected project")
            request = command.model_dump(exclude={"explicit_rebuild_confirmed"})
            return {"project_id": project_id, **materialize_map_sources(root, request)}
        return run(project_id, build)

    @router.post(prefix + "/rudy/drafts", status_code=201)
    def draft(project_id: str, command: PlannedRudyDraftCommand):
        request = {"label": command.label, "geometry": command.geometry, "map_evidence": command.map_evidence,
            "reviewed_by": command.created_by, "reviewer_kind": "software", "trace_author_kind": "software",
            "review_note": command.review_note, "candidate_review_confirmed": True}
        return run(project_id, lambda root: {"project_id": project_id, **materialize_rudy_trace(root, request)})

    @router.post(prefix + "/versions/{version_id}/human-review", status_code=201)
    def human_review(project_id: str, version_id: str, command: PlannedMapHumanReviewCommand):
        def review(root):
            current = inspect(root, version_id)
            manifest = current["manifest"]
            if current["manifest_sha256"] != command.expected_manifest_sha256:
                raise ValueError("The reviewed map manifest changed; reload before confirming")
            if manifest["kind"] != "rudy_trace" or manifest["source_state"] != "pending_human_review":
                raise ValueError("Explicit human review applies only to a pending Rudy trace")
            draft_request = manifest["request"]
            request = {key: draft_request[key] for key in ("label", "geometry", "map_evidence")}
            request.update(reviewed_by=command.reviewer_name, reviewer_kind="human",
                trace_author_kind=draft_request.get("trace_author_kind") or draft_request["reviewer_kind"],
                review_note=command.review_note, candidate_review_confirmed=True,
                reviewed_draft_ref=current["manifest_ref"], reviewed_draft_sha256=current["manifest_sha256"])
            return {"project_id": project_id, "reviewed_materialization_id": version_id,
                    **materialize_rudy_trace(root, PlannedRudyTraceRequest.model_validate(request))}
        return run(project_id, review)

    return router
