from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


DEFAULT_RUNTIME_ARTIFACT_RESOLUTION_MANIFEST_NAME = (
    "runtime_artifact_resolution_manifest.json"
)
SYMBOLIC_ARTIFACT_PREFIX = "artifact:"


def resolve_runtime_route_source(
    mission_graph_path: Path | str,
    route_source: str,
    resolution_manifest_path: Path | str | None = None,
) -> Path:
    mission_path = Path(mission_graph_path)
    if not route_source.startswith(SYMBOLIC_ARTIFACT_PREFIX):
        return _resolve_plain_route_source(mission_path, route_source)

    manifest_path = _default_manifest_path(mission_path, resolution_manifest_path)
    if not manifest_path.is_file():
        raise FileNotFoundError(
            f"artifact resolution manifest missing for {route_source}: {manifest_path}"
        )
    manifest = _load_manifest_payload(manifest_path)
    resolution = _resolution_for_route_source(manifest, route_source)
    if not resolution.get("resolved"):
        raise FileNotFoundError(f"runtime route artifact is not resolved: {route_source}")

    runtime_ref = str(resolution.get("runtime_ref") or "")
    _assert_relative_runtime_ref(runtime_ref)
    route_path = (manifest_path.parent / runtime_ref).resolve()
    try:
        route_path.relative_to(manifest_path.parent.resolve())
    except ValueError as exc:
        raise ValueError("runtime route artifact must stay inside export root") from exc
    if not route_path.is_file():
        raise FileNotFoundError(f"runtime route artifact missing: {route_path}")

    expected_sha = resolution.get("sha256")
    if expected_sha is not None:
        actual_sha = _sha256_file(route_path)
        if actual_sha != expected_sha:
            raise ValueError(
                f"runtime route artifact hash mismatch for {route_source}: {actual_sha}"
            )
    return route_path


def _default_manifest_path(
    mission_graph_path: Path,
    resolution_manifest_path: Path | str | None,
) -> Path:
    if resolution_manifest_path is not None:
        return Path(resolution_manifest_path)
    return mission_graph_path.parent / DEFAULT_RUNTIME_ARTIFACT_RESOLUTION_MANIFEST_NAME


def _resolve_plain_route_source(mission_graph_path: Path, route_source: str) -> Path:
    route_path = Path(route_source)
    if route_path.is_absolute():
        return route_path

    candidates = [
        Path.cwd() / route_path,
        mission_graph_path.parent / route_path,
        mission_graph_path.parent.parent.parent / route_path,
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


def _load_manifest_payload(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("artifact resolution manifest must be a JSON object")
    return payload


def _resolution_for_route_source(
    manifest: dict[str, Any],
    route_source: str,
) -> dict[str, Any]:
    resolutions = manifest.get("resolutions")
    if not isinstance(resolutions, list):
        raise ValueError("artifact resolution manifest must include resolutions")
    for resolution in resolutions:
        if isinstance(resolution, dict) and resolution.get("artifact_ref") == route_source:
            return resolution
    raise FileNotFoundError(f"route source artifact has no resolution: {route_source}")


def _assert_relative_runtime_ref(value: str) -> None:
    path = Path(value)
    if not value or path.is_absolute() or ".." in path.parts:
        raise ValueError("runtime_ref must be a relative runtime artifact path")


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()
