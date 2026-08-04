"""Persistent, single-flight delivery for Navigation & Terrain Intelligence."""

from __future__ import annotations

import hashlib
import json
import os
import threading
from concurrent.futures import Executor, Future, ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from navigation_terrain_projection import (
    NAVIGATION_TERRAIN_SCHEMA_VERSION,
    NavigationTerrainProjectionError,
    build_navigation_terrain_projection,
)


NAVIGATION_TERRAIN_PROJECTION_REF = (
    "outputs/navigation/navigation_terrain_intelligence.json"
)
NAVIGATION_TERRAIN_PROJECTION_STATUS_ARTIFACT_KIND = (
    "navigation_terrain_intelligence_projection_status"
)
NAVIGATION_TERRAIN_PROJECTION_INPUT_REF_KEYS = (
    "terrain_visualization_ref",
    "terrain_route_samples_ref",
    "terrain_risk_candidates_ref",
    "terrain_slope_shading_overlay_ref",
    "dtm_coverage_summary_ref",
    "historical_gpx_source_index_ref",
    "historical_route_source_ledger_ref",
    "normalized_route_note_candidates_ref",
    "historical_route_hypothesis_ref",
    "terrain_expert_annotation_refs",
    "terrain_acceptance_policy_ref",
)


@dataclass(frozen=True)
class NavigationTerrainProjectionResolution:
    http_status: int
    payload: dict[str, Any]


@dataclass(frozen=True)
class _ProjectionJob:
    input_fingerprint: str
    future: Future[dict[str, Any]]


class NavigationTerrainProjectionCoordinator:
    """Coalesce one cold projection build per workspace."""

    def __init__(self, *, executor: Executor | None = None) -> None:
        self._executor = executor or ThreadPoolExecutor(
            max_workers=2,
            thread_name_prefix="scout-navigation-terrain",
        )
        self._lock = threading.Lock()
        self._jobs: dict[str, _ProjectionJob] = {}

    def resolve(
        self,
        project_root: Path,
        project: dict[str, Any],
        *,
        project_id: str,
    ) -> NavigationTerrainProjectionResolution:
        root = project_root.resolve()
        fingerprint = navigation_terrain_input_fingerprint(root, project)
        persisted = load_persisted_navigation_terrain_projection(
            root,
            project,
            input_fingerprint=fingerprint,
        )
        if persisted is not None:
            return NavigationTerrainProjectionResolution(
                http_status=200,
                payload=_with_delivery(
                    persisted,
                    served_from="persisted_workspace_artifact",
                ),
            )

        job_key = str(root)
        with self._lock:
            job = self._jobs.get(job_key)
            if job is not None and job.future.done():
                self._jobs.pop(job_key, None)
                try:
                    completed = job.future.result()
                except Exception as exc:  # pragma: no cover - defensive worker boundary.
                    return NavigationTerrainProjectionResolution(
                        http_status=200,
                        payload=_failed_payload(
                            project_id=project_id,
                            input_fingerprint=job.input_fingerprint,
                            error_type=type(exc).__name__,
                        ),
                    )
                completed_fingerprint = str(
                    completed.get("projection_compilation", {}).get(
                        "input_fingerprint"
                    )
                    or ""
                )
                if completed_fingerprint == fingerprint:
                    return NavigationTerrainProjectionResolution(
                        http_status=200,
                        payload=_with_delivery(
                            completed,
                            served_from="completed_single_flight_job",
                        ),
                    )
                job = None

            if job is None:
                try:
                    future = self._executor.submit(
                        compile_navigation_terrain_projection,
                        root,
                        dict(project),
                        project_id,
                    )
                except Exception as exc:  # pragma: no cover - executor failure.
                    return NavigationTerrainProjectionResolution(
                        http_status=200,
                        payload=_failed_payload(
                            project_id=project_id,
                            input_fingerprint=fingerprint,
                            error_type=type(exc).__name__,
                        ),
                    )
                job = _ProjectionJob(
                    input_fingerprint=fingerprint,
                    future=future,
                )
                self._jobs[job_key] = job
                job_state = "started"
            else:
                job_state = "coalesced"

        return NavigationTerrainProjectionResolution(
            http_status=202,
            payload=_preparing_payload(
                project_id=project_id,
                input_fingerprint=fingerprint,
                job_state=job_state,
            ),
        )


def compile_navigation_terrain_projection(
    project_root: Path,
    project: dict[str, Any] | None = None,
    project_id: str | None = None,
    *,
    compiled_at: str | None = None,
) -> dict[str, Any]:
    """Compile and atomically persist a bounded, candidate-only projection."""

    root = project_root.resolve()
    source_project = dict(project) if isinstance(project, dict) else _load_project(root)
    resolved_project_id = str(
        project_id
        or source_project.get("project_id")
        or source_project.get("id")
        or root.name
    )
    fingerprint = navigation_terrain_input_fingerprint(root, source_project)
    projection = build_navigation_terrain_projection(
        root,
        source_project,
        project_id=resolved_project_id,
    )
    evaluated_at = compiled_at or _utc_now()
    payload = {
        **projection,
        "projection_state": "ready",
        "projection_compilation": {
            "status": "ready",
            "compiled_at": evaluated_at,
            "input_fingerprint": fingerprint,
            "source_ref": NAVIGATION_TERRAIN_PROJECTION_REF,
            "compiler": "navigation_terrain_projection_store.v1",
            "candidate_only": True,
            "runtime_safety_truth": False,
        },
    }
    artifact_path = _safe_project_path(root, NAVIGATION_TERRAIN_PROJECTION_REF)
    _write_json_atomic(artifact_path, payload)
    _update_project_projection_ref(
        root,
        {
            "navigation_terrain_projection_ref": NAVIGATION_TERRAIN_PROJECTION_REF,
            "navigation_terrain_projection_status": "ready",
            "navigation_terrain_projection_input_fingerprint": fingerprint,
            "navigation_terrain_projection_compiled_at": evaluated_at,
        },
    )
    return payload


def resolve_navigation_terrain_projection(
    project_root: Path,
    project: dict[str, Any],
    *,
    project_id: str,
) -> NavigationTerrainProjectionResolution:
    return _DEFAULT_COORDINATOR.resolve(
        project_root,
        project,
        project_id=project_id,
    )


def load_persisted_navigation_terrain_projection(
    project_root: Path,
    project: dict[str, Any],
    *,
    input_fingerprint: str | None = None,
) -> dict[str, Any] | None:
    root = project_root.resolve()
    raw_ref = project.get("navigation_terrain_projection_ref")
    ref = (
        str(raw_ref).strip()
        if isinstance(raw_ref, str) and raw_ref.strip()
        else NAVIGATION_TERRAIN_PROJECTION_REF
    )
    path = _safe_project_path(root, ref)
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    compilation = payload.get("projection_compilation")
    if not isinstance(compilation, dict):
        return None
    expected_fingerprint = input_fingerprint or navigation_terrain_input_fingerprint(
        root,
        project,
    )
    if compilation.get("input_fingerprint") != expected_fingerprint:
        return None
    boundary = payload.get("boundary")
    if (
        not isinstance(boundary, dict)
        or boundary.get("candidate_only") is not True
        or boundary.get("runtime_safety_truth") is not False
    ):
        return None
    return payload


def navigation_terrain_input_fingerprint(
    project_root: Path,
    project: dict[str, Any],
) -> str:
    root = project_root.resolve()
    states: list[dict[str, Any]] = []
    for key in NAVIGATION_TERRAIN_PROJECTION_INPUT_REF_KEYS:
        raw_ref = project.get(key)
        if isinstance(raw_ref, str):
            refs = [raw_ref.strip()] if raw_ref.strip() else []
        elif isinstance(raw_ref, list):
            refs = [
                item.strip()
                for item in raw_ref
                if isinstance(item, str) and item.strip()
            ]
        else:
            refs = []
        if not refs:
            states.append({"key": key, "ref": None, "size": None, "mtime_ns": None})
            continue
        for ref_index, ref in enumerate(dict.fromkeys(refs)):
            path = _safe_project_path(root, ref)
            try:
                stat = path.stat()
            except OSError:
                states.append(
                    {
                        "key": key,
                        "ref_index": ref_index,
                        "ref": ref,
                        "size": None,
                        "mtime_ns": None,
                    }
                )
                continue
            states.append(
                {
                    "key": key,
                    "ref_index": ref_index,
                    "ref": ref,
                    "size": stat.st_size,
                    "mtime_ns": stat.st_mtime_ns,
                }
            )
    encoded = json.dumps(
        states,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _preparing_payload(
    *,
    project_id: str,
    input_fingerprint: str,
    job_state: str,
) -> dict[str, Any]:
    return {
        "schema_version": NAVIGATION_TERRAIN_SCHEMA_VERSION,
        "artifact_kind": NAVIGATION_TERRAIN_PROJECTION_STATUS_ARTIFACT_KIND,
        "project_id": project_id,
        "status": "preparing",
        "projection_state": "preparing",
        "job_state": job_state,
        "input_fingerprint": input_fingerprint,
        "source_ref": NAVIGATION_TERRAIN_PROJECTION_REF,
        "retry_after_ms": 1000,
        "summary": "Compiling prepared DTM and route evidence.",
        "boundary": _candidate_boundary(),
    }


def _failed_payload(
    *,
    project_id: str,
    input_fingerprint: str,
    error_type: str,
) -> dict[str, Any]:
    return {
        "schema_version": NAVIGATION_TERRAIN_SCHEMA_VERSION,
        "artifact_kind": NAVIGATION_TERRAIN_PROJECTION_STATUS_ARTIFACT_KIND,
        "project_id": project_id,
        "status": "failed",
        "projection_state": "failed",
        "input_fingerprint": input_fingerprint,
        "source_ref": NAVIGATION_TERRAIN_PROJECTION_REF,
        "retry_after_ms": None,
        "error_type": error_type[:120],
        "summary": "Projection build failed; workspace evidence requires review.",
        "boundary": _candidate_boundary(),
    }


def _with_delivery(
    payload: dict[str, Any],
    *,
    served_from: str,
) -> dict[str, Any]:
    return {
        **payload,
        "projection_delivery": {
            "served_from": served_from,
            "synchronous_rebuild_performed": False,
        },
    }


def _candidate_boundary() -> dict[str, Any]:
    return {
        "candidate_only": True,
        "runtime_safety_truth": False,
        "safe_or_walkable": "not_determined",
        "phase1_runtime_mutation_allowed": False,
        "human_review_required": True,
    }


def _load_project(project_root: Path) -> dict[str, Any]:
    path = project_root / "project.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise NavigationTerrainProjectionError(
            "navigation terrain project metadata could not be read"
        ) from exc
    if not isinstance(payload, dict):
        raise NavigationTerrainProjectionError(
            "navigation terrain project metadata must be an object"
        )
    return payload


def _update_project_projection_ref(
    project_root: Path,
    updates: dict[str, Any],
) -> None:
    project_path = project_root / "project.json"
    current = _load_project(project_root)
    _write_json_atomic(project_path, {**current, **updates})


def _safe_project_path(project_root: Path, ref: str) -> Path:
    candidate_ref = Path(ref)
    if candidate_ref.is_absolute() or ".." in candidate_ref.parts:
        raise NavigationTerrainProjectionError(
            "unsafe navigation terrain projection artifact reference"
        )
    candidate = (project_root / candidate_ref).resolve()
    try:
        candidate.relative_to(project_root)
    except ValueError as exc:
        raise NavigationTerrainProjectionError(
            "unsafe navigation terrain projection artifact reference"
        ) from exc
    return candidate


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(
        f".{path.name}.tmp-{os.getpid()}-{threading.get_ident()}"
    )
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _utc_now() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


_DEFAULT_COORDINATOR = NavigationTerrainProjectionCoordinator()


__all__ = [
    "NAVIGATION_TERRAIN_PROJECTION_REF",
    "NavigationTerrainProjectionCoordinator",
    "NavigationTerrainProjectionResolution",
    "compile_navigation_terrain_projection",
    "load_persisted_navigation_terrain_projection",
    "navigation_terrain_input_fingerprint",
    "resolve_navigation_terrain_projection",
]
