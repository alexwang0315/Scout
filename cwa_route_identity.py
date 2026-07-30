from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping
from pathlib import Path
from typing import Any


MAX_ROUTE_ARTIFACT_BYTES = 64 * 1024 * 1024
EXPECTED_ROUTE_ARTIFACT_KINDS = {
    "overpass_aligned_segment_display_geometry_ref": (
        "pretrip_overpass_aligned_segment_display_geometry"
    ),
    "segment_display_geometry_ref": "pretrip_segment_display_geometry",
}


def load_cwa_route_identity(
    project_root: Path | str,
    project: Mapping[str, Any],
    max_points: int = 2_000,
) -> tuple[dict[str, Any], list[tuple[float, float]]]:
    """Load the active route geometry and bind it to immutable provenance.

    Overpass-aligned display geometry is authoritative for CWA-derived display
    evidence when present. The importer display geometry remains the safe
    fallback. Returned route points may be sampled for bounded processing, but
    ``pointCount`` records the unsampled artifact point count.
    """

    if (
        isinstance(max_points, bool)
        or not isinstance(max_points, int)
        or max_points < 2
    ):
        raise ValueError("max_points must be an integer of at least two")
    root = Path(project_root).expanduser().resolve()
    project_id = str(project.get("project_id") or "").strip()
    if not project_id:
        raise ValueError("CWA route identity requires project_id")

    candidates = (
        (
            "overpass_aligned_segment_display_geometry_ref",
            "overpass_aligned_segment_display_geometry",
        ),
        ("segment_display_geometry_ref", "segment_display_geometry"),
    )
    for ref_key, route_basis in candidates:
        ref = project.get(ref_key)
        if not isinstance(ref, str) or not ref.strip():
            continue
        normalized_ref = ref.strip()
        path = _safe_project_ref(root, normalized_ref)
        if not path.is_file():
            continue
        with path.open("rb") as handle:
            raw = handle.read(MAX_ROUTE_ARTIFACT_BYTES + 1)
        if len(raw) > MAX_ROUTE_ARTIFACT_BYTES:
            raise ValueError("CWA route artifact exceeds size limit")
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError("CWA route artifact is invalid JSON") from exc
        _validate_route_artifact_identity(
            payload,
            project_id=project_id,
            expected_artifact_kind=EXPECTED_ROUTE_ARTIFACT_KINDS[ref_key],
        )
        all_points = _route_points(payload)
        if len(all_points) < 2:
            continue
        identity = {
            "projectId": project_id,
            "routeRef": normalized_ref,
            "routeSha256": _route_geometry_sha256(all_points),
            "routeBasis": route_basis,
            "pointCount": len(all_points),
        }
        return identity, _bounded_points(all_points, max_points=max_points)

    raise ValueError("CWA route geometry is not prepared")


def validate_cwa_artifact_route_identity(
    project_root: Path | str,
    project: Mapping[str, Any],
    artifact: Mapping[str, Any],
    *,
    artifact_label: str,
) -> str:
    """Validate a derived CWA artifact against the current project route."""

    project_id = str(project.get("project_id") or "").strip()
    if not project_id:
        raise ValueError("current project identity is unavailable")
    artifact_project_id = artifact.get("projectId")
    if artifact_project_id is not None and str(artifact_project_id) != project_id:
        raise ValueError(f"{artifact_label} project identity mismatch")
    artifact_route_sha = artifact.get("routeSha256")
    if not isinstance(artifact_route_sha, str) or not artifact_route_sha:
        return "legacy_unverified"
    current_identity, _route_points = load_cwa_route_identity(project_root, project)
    for key in ("projectId", "routeRef", "routeBasis"):
        artifact_value = artifact.get(key)
        if artifact_value is not None and artifact_value != current_identity.get(key):
            raise ValueError(f"{artifact_label} route identity mismatch")
    if artifact_route_sha != current_identity["routeSha256"]:
        legacy_raw_sha256 = _legacy_route_artifact_sha256(
            project_root,
            str(current_identity["routeRef"]),
        )
        if artifact_route_sha != legacy_raw_sha256:
            raise ValueError(f"{artifact_label} route identity mismatch")
    return "verified"


def validate_cwa_pair_identity(
    first: Mapping[str, Any],
    second: Mapping[str, Any],
    *,
    first_label: str,
    second_label: str,
) -> str:
    """Require matching pair/frame provenance when either artifact declares it."""

    first_pair = _pair_identity(first, label=first_label)
    second_pair = _pair_identity(second, label=second_label)
    if first_pair is None and second_pair is None:
        return "legacy_unverified"
    if first_pair is None or second_pair is None or first_pair != second_pair:
        raise ValueError(f"{first_label} and {second_label} pair identity mismatch")
    return "verified"


def _validate_route_artifact_identity(
    payload: Any,
    *,
    project_id: str,
    expected_artifact_kind: str,
) -> None:
    if not isinstance(payload, dict):
        raise ValueError("CWA route artifact contract is invalid")
    if payload.get("artifact_kind") != expected_artifact_kind:
        raise ValueError("CWA route artifact kind mismatch")
    embedded_project_id = payload.get("project_id", payload.get("projectId"))
    if str(embedded_project_id or "").strip() != project_id:
        raise ValueError("CWA route artifact project identity mismatch")
    route_artifact_id = payload.get("route_artifact_id")
    if route_artifact_id is not None and route_artifact_id != f"artifact.gpx.{project_id}":
        raise ValueError("CWA route artifact project identity mismatch")
    for segment in payload.get("segments", []):
        if not isinstance(segment, dict):
            continue
        segment_project_id = segment.get("project_id", segment.get("projectId"))
        if segment_project_id is not None and str(segment_project_id).strip() != project_id:
            raise ValueError("CWA route segment project identity mismatch")
        segment_route_artifact_id = segment.get("route_artifact_id")
        if (
            segment_route_artifact_id is not None
            and segment_route_artifact_id != f"artifact.gpx.{project_id}"
        ):
            raise ValueError("CWA route segment project identity mismatch")


def _route_geometry_sha256(points: list[tuple[float, float]]) -> str:
    canonical_geometry = json.dumps(
        [[lat, lon] for lat, lon in points],
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canonical_geometry).hexdigest()


def _legacy_route_artifact_sha256(
    project_root: Path | str,
    route_ref: str,
) -> str:
    root = Path(project_root).expanduser().resolve()
    path = _safe_project_ref(root, route_ref)
    with path.open("rb") as handle:
        raw = handle.read(MAX_ROUTE_ARTIFACT_BYTES + 1)
    if len(raw) > MAX_ROUTE_ARTIFACT_BYTES:
        raise ValueError("CWA route artifact exceeds size limit")
    return hashlib.sha256(raw).hexdigest()


def _pair_identity(
    artifact: Mapping[str, Any],
    *,
    label: str,
) -> tuple[str, tuple[tuple[str, str], ...]] | None:
    pair_id = artifact.get("pairId")
    source_frame_ids = artifact.get("sourceFrameIds")
    if pair_id is None and source_frame_ids is None:
        return None
    if not isinstance(pair_id, str) or not pair_id.strip():
        raise ValueError(f"{label} pair identity is incomplete")
    if not isinstance(source_frame_ids, Mapping) or not source_frame_ids:
        raise ValueError(f"{label} pair identity is incomplete")
    normalized_frames: list[tuple[str, str]] = []
    for kind, frame_id in source_frame_ids.items():
        normalized_kind = str(kind).strip()
        normalized_frame_id = str(frame_id).strip()
        if not normalized_kind or not normalized_frame_id:
            raise ValueError(f"{label} pair identity is invalid")
        normalized_frames.append((normalized_kind, normalized_frame_id))
    return pair_id.strip(), tuple(sorted(normalized_frames))


def _safe_project_ref(root: Path, ref: str) -> Path:
    candidate = Path(ref)
    if candidate.is_absolute() or any(part in {".", ".."} for part in candidate.parts):
        raise ValueError("unsafe CWA route ref")
    resolved = (root / candidate).resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ValueError("CWA route ref escapes project root") from exc
    return resolved


def _route_points(payload: Any) -> list[tuple[float, float]]:
    segments = payload.get("segments", []) if isinstance(payload, dict) else []
    if not isinstance(segments, list):
        return []
    points: list[tuple[float, float]] = []
    for segment in segments:
        if not isinstance(segment, dict):
            continue
        coordinate_segments = segment.get("coordinate_segments")
        if not isinstance(coordinate_segments, list):
            coordinates = segment.get("coordinates")
            coordinate_segments = [coordinates] if isinstance(coordinates, list) else []
        for coordinate_segment in coordinate_segments:
            if not isinstance(coordinate_segment, list):
                continue
            for point in coordinate_segment:
                normalized = _point(point)
                if normalized is not None and (not points or points[-1] != normalized):
                    points.append(normalized)
    return points


def _point(value: Any) -> tuple[float, float] | None:
    if not isinstance(value, dict):
        return None
    try:
        lat = float(value.get("lat"))
        lon = float(value.get("lon"))
    except (TypeError, ValueError):
        return None
    if not math.isfinite(lat) or not math.isfinite(lon):
        return None
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return None
    return lat, lon


def _bounded_points(
    points: list[tuple[float, float]],
    *,
    max_points: int,
) -> list[tuple[float, float]]:
    if len(points) <= max_points:
        return list(points)
    last_index = len(points) - 1
    indexes = {
        round(position * last_index / (max_points - 1))
        for position in range(max_points)
    }
    indexes.update({0, last_index})
    return [points[index] for index in sorted(indexes)]
