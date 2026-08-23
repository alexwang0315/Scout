from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
from typing import Any


QGIS_SPATIAL_RISK_INPUT_REFS = {
    "qgis_spatial_risk_inputs_ref": "outputs/risk/qgis_spatial_risk_inputs.geojson",
    "qgis_spatial_risk_inputs_metadata_ref": (
        "outputs/risk/qgis_spatial_risk_inputs.metadata.json"
    ),
}
_WORKFLOW_ID = "terrain_feature_stack.v1"
_ROUTE_SAMPLE_ARTIFACT_TYPE = "terrain_feature_route_samples"
_MAX_QGIS_RUNS = 1000
_MAX_ROUTE_FEATURES = 20_000
_MAX_QGIS_SAMPLES = 128
_DEFAULT_ALIGNMENT_DISTANCE_M = 60.0


class SpatialRiskInputError(ValueError):
    pass


def build_qgis_spatial_risk_inputs(
    *,
    route_risk_path: Path,
    qgis_route_samples_path: Path,
    qgis_workflow_run_id: str,
    qgis_workflow_run_ref: str,
    qgis_human_review_status: str = "unknown",
    max_alignment_distance_m: float = _DEFAULT_ALIGNMENT_DISTANCE_M,
) -> dict[str, Any]:
    if not 0 < max_alignment_distance_m <= 250:
        raise SpatialRiskInputError("max alignment distance is outside the bounded range")
    route_risk = _load_feature_collection(
        route_risk_path,
        label="route risk",
        max_features=_MAX_ROUTE_FEATURES,
    )
    qgis_samples = _load_feature_collection(
        qgis_route_samples_path,
        label="QGIS route terrain samples",
        max_features=_MAX_QGIS_SAMPLES,
    )
    _validate_qgis_sample_authority(qgis_samples)
    indexed_samples = _indexed_qgis_samples(qgis_samples)
    if not indexed_samples:
        raise SpatialRiskInputError("QGIS route terrain samples contain no valid points")

    features: list[dict[str, Any]] = []
    aligned_count = 0
    for index, feature in enumerate(route_risk["features"]):
        geometry = feature.get("geometry") if isinstance(feature, dict) else None
        coordinates = geometry.get("coordinates") if isinstance(geometry, dict) else None
        if (
            not isinstance(geometry, dict)
            or geometry.get("type") != "Point"
            or not isinstance(coordinates, list)
            or len(coordinates) < 2
        ):
            continue
        lon = _finite_float(coordinates[0])
        lat = _finite_float(coordinates[1])
        if lon is None or lat is None or not (-180 <= lon <= 180 and -90 <= lat <= 90):
            continue
        nearest, distance_m = min(
            (
                (sample, _haversine_m(lat, lon, sample["lat"], sample["lon"]))
                for sample in indexed_samples
            ),
            key=lambda item: item[1],
        )
        aligned = distance_m <= max_alignment_distance_m
        source_properties = dict(feature.get("properties") or {})
        sample_properties = nearest["properties"] if aligned else {}
        if aligned:
            aligned_count += 1
        sample_id = str(
            source_properties.get("sample_id") or f"route-risk-sample.{index:05d}"
        )
        properties = {
            "spatial_input_id": f"qgis-spatial-risk-input.{sample_id}",
            "route_id": source_properties.get("route_id"),
            "route_sample_id": sample_id,
            "distance_m": source_properties.get("distance_m"),
            "baseline_pretrip_risk": source_properties.get("pretrip_risk"),
            "baseline_teii_20m": source_properties.get("teii_20m"),
            "alignment_status": "aligned" if aligned else "no_nearby_qgis_sample",
            "qgis_sample_id": sample_properties.get("sample_id") if aligned else None,
            "qgis_sample_distance_m": round(distance_m, 2),
            "slope_degrees": sample_properties.get("slope_degrees"),
            "aspect_degrees": sample_properties.get("aspect_degrees"),
            "geomorphon_code": sample_properties.get("geomorphon_code"),
            "geomorphon_label": sample_properties.get("geomorphon_label"),
            "flow_accumulation_cells": sample_properties.get(
                "flow_accumulation_cells"
            ),
            "flow_accumulation_abs_cells": sample_properties.get(
                "flow_accumulation_abs_cells"
            ),
            "flow_accumulation_likely_underestimated": sample_properties.get(
                "flow_accumulation_likely_underestimated"
            ),
            "qgis_workflow_run_id": qgis_workflow_run_id,
            "candidate_only": True,
            "runtime_safety_truth": False,
            "operational": False,
            "risk_score_applied": False,
            "baseline_score_modified": False,
            "risk_v2_status": "calibration_required" if aligned else "input_unavailable",
        }
        features.append(
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [lon, lat]},
                "properties": properties,
            }
        )

    status = "ready_for_calibration" if aligned_count else "insufficient_alignment"
    metadata = {
        "artifact_kind": "scout_qgis_spatial_risk_inputs",
        "schema_version": "scout_qgis_spatial_risk_inputs.v0_1",
        "status": status,
        "source_route_risk_ref": str(route_risk_path),
        "source_route_risk_sha256": _sha256_file(route_risk_path),
        "source_qgis_route_samples_ref": str(qgis_route_samples_path),
        "source_qgis_route_samples_sha256": _sha256_file(qgis_route_samples_path),
        "qgis_workflow_id": _WORKFLOW_ID,
        "qgis_workflow_run_id": qgis_workflow_run_id,
        "qgis_workflow_run_ref": qgis_workflow_run_ref,
        "qgis_human_review_status": qgis_human_review_status,
        "alignment_method": "nearest_wgs84_route_sample",
        "max_alignment_distance_m": max_alignment_distance_m,
        "source_route_sample_count": len(route_risk["features"]),
        "output_sample_count": len(features),
        "qgis_sample_count": len(indexed_samples),
        "aligned_sample_count": aligned_count,
        "unaligned_sample_count": len(features) - aligned_count,
        "candidate_only": True,
        "runtime_safety_truth": False,
        "operational": False,
        "risk_score_applied": False,
        "baseline_scores_modified": False,
        "risk_v2_status": "calibration_required",
        "warnings": [
            "QGIS/GRASS terrain values are candidate risk-model inputs only.",
            "No terrain, hazard, route, navigability, trail, or safety conclusion was generated.",
            "Existing risk-ribbon, risk-heatmap, and risk-delta scores were not modified.",
        ],
    }
    return {"type": "FeatureCollection", "metadata": metadata, "features": features}


def sync_reviewed_qgis_spatial_risk_inputs(
    *,
    project_root: Path,
    project: dict[str, Any],
) -> dict[str, Any]:
    route_ref = project.get("risk_route_profile_ref")
    if not isinstance(route_ref, str) or not route_ref:
        return {
            **project,
            "qgis_spatial_risk_input_status": "not_available",
            "qgis_spatial_risk_input_reason": "risk_route_profile_ref_missing",
        }
    route_path = _safe_project_path(project_root, route_ref)
    if not route_path.is_file():
        return {
            **project,
            "qgis_spatial_risk_input_status": "not_available",
            "qgis_spatial_risk_input_reason": "risk_route_profile_missing",
        }
    reviewed = _latest_reviewed_qgis_route_samples(project_root)
    if reviewed is None:
        return {
            **project,
            "qgis_spatial_risk_input_status": "not_available",
            "qgis_spatial_risk_input_reason": "reviewed_qgis_feature_stack_missing",
        }
    run, run_ref, samples_path = reviewed
    try:
        payload = build_qgis_spatial_risk_inputs(
            route_risk_path=route_path,
            qgis_route_samples_path=samples_path,
            qgis_workflow_run_id=str(run["workflow_run_id"]),
            qgis_workflow_run_ref=run_ref,
            qgis_human_review_status="completed",
        )
    except (OSError, KeyError, TypeError, SpatialRiskInputError) as exc:
        return {
            **project,
            "qgis_spatial_risk_input_status": "failed",
            "qgis_spatial_risk_input_reason": type(exc).__name__,
        }

    output_ref = QGIS_SPATIAL_RISK_INPUT_REFS["qgis_spatial_risk_inputs_ref"]
    metadata_ref = QGIS_SPATIAL_RISK_INPUT_REFS[
        "qgis_spatial_risk_inputs_metadata_ref"
    ]
    _write_json(_safe_project_path(project_root, output_ref), payload)
    _write_json(_safe_project_path(project_root, metadata_ref), payload["metadata"])
    return {
        **project,
        **QGIS_SPATIAL_RISK_INPUT_REFS,
        "qgis_spatial_risk_input_status": payload["metadata"]["status"],
        "qgis_spatial_risk_input_aligned_count": payload["metadata"][
            "aligned_sample_count"
        ],
        "qgis_spatial_risk_input_workflow_run_id": run["workflow_run_id"],
        "qgis_spatial_risk_input_candidate_only": True,
        "qgis_spatial_risk_input_runtime_safety_truth": False,
        "qgis_spatial_risk_input_operational": False,
        "qgis_spatial_risk_input_score_applied": False,
    }


def _latest_reviewed_qgis_route_samples(
    project_root: Path,
) -> tuple[dict[str, Any], str, Path] | None:
    root = _safe_project_path(project_root, "outputs/spatial/qgis")
    if not root.is_dir():
        return None
    candidates: list[tuple[str, dict[str, Any], str, Path]] = []
    for run_path in list(root.glob("*/workflow_run.json"))[:_MAX_QGIS_RUNS]:
        try:
            run = json.loads(run_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not _reviewed_feature_stack_run(run):
            continue
        artifact = next(
            (
                item
                for item in run.get("artifacts", [])
                if isinstance(item, dict)
                and item.get("artifact_type") == _ROUTE_SAMPLE_ARTIFACT_TYPE
                and item.get("status") == "reviewed_evidence"
                and item.get("fixture") is False
                and item.get("synthetic") is False
            ),
            None,
        )
        if artifact is None:
            continue
        artifact_ref = artifact.get("artifact_ref")
        artifact_hash = artifact.get("artifact_hash")
        if not isinstance(artifact_ref, str) or not isinstance(artifact_hash, str):
            continue
        try:
            samples_path = _safe_project_path(project_root, artifact_ref)
        except SpatialRiskInputError:
            continue
        if not samples_path.is_file() or _sha256_file(samples_path) != artifact_hash:
            continue
        run_ref = run_path.resolve().relative_to(project_root.resolve()).as_posix()
        candidates.append(
            (str(run.get("completed_at") or ""), run, run_ref, samples_path)
        )
    if not candidates:
        return None
    _, run, run_ref, samples_path = max(candidates, key=lambda item: item[0])
    return run, run_ref, samples_path


def _reviewed_feature_stack_run(run: dict[str, Any]) -> bool:
    return bool(
        run.get("workflow_id") == _WORKFLOW_ID
        and run.get("state") == "completed"
        and run.get("human_review_status") == "completed"
        and run.get("visual_review_status") == "completed"
        and run.get("candidate_only") is True
        and run.get("runtime_safety_truth") is False
        and run.get("operational") is False
    )


def _validate_qgis_sample_authority(payload: dict[str, Any]) -> None:
    metadata = payload.get("metadata")
    if not isinstance(metadata, dict) or any(
        (
            metadata.get("candidate_only") is not True,
            metadata.get("runtime_safety_truth") is not False,
            metadata.get("operational") is not False,
            metadata.get("risk_score_applied") is not False,
        )
    ):
        raise SpatialRiskInputError("QGIS sample candidate authority is invalid")
    for feature in payload["features"]:
        properties = feature.get("properties") if isinstance(feature, dict) else None
        if not isinstance(properties, dict) or any(
            (
                properties.get("candidate_only") is not True,
                properties.get("runtime_safety_truth") is not False,
                properties.get("operational") is not False,
                properties.get("risk_score_applied") is not False,
            )
        ):
            raise SpatialRiskInputError("QGIS sample candidate authority is invalid")


def _indexed_qgis_samples(payload: dict[str, Any]) -> list[dict[str, Any]]:
    samples: list[dict[str, Any]] = []
    for feature in payload["features"]:
        geometry = feature.get("geometry") if isinstance(feature, dict) else None
        coordinates = geometry.get("coordinates") if isinstance(geometry, dict) else None
        if (
            not isinstance(geometry, dict)
            or geometry.get("type") != "Point"
            or not isinstance(coordinates, list)
            or len(coordinates) < 2
        ):
            continue
        lon = _finite_float(coordinates[0])
        lat = _finite_float(coordinates[1])
        if lon is None or lat is None:
            continue
        samples.append(
            {
                "lon": lon,
                "lat": lat,
                "properties": dict(feature.get("properties") or {}),
            }
        )
    return samples


def _load_feature_collection(
    path: Path,
    *,
    label: str,
    max_features: int,
) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SpatialRiskInputError(f"{label} is unavailable or malformed") from exc
    features = payload.get("features") if isinstance(payload, dict) else None
    if (
        not isinstance(payload, dict)
        or payload.get("type") != "FeatureCollection"
        or not isinstance(features, list)
        or not 1 <= len(features) <= max_features
    ):
        raise SpatialRiskInputError(f"{label} is outside the bounded GeoJSON contract")
    return payload


def _safe_project_path(project_root: Path, ref: str) -> Path:
    candidate = Path(ref)
    if candidate.is_absolute() or ".." in candidate.parts:
        raise SpatialRiskInputError("spatial risk input ref is outside the project")
    root = project_root.expanduser().resolve()
    path = (root / candidate).resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise SpatialRiskInputError("spatial risk input ref is outside the project") from exc
    return path


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = (
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    temporary.write_bytes(raw)
    temporary.replace(path)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _finite_float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius_m = 6_371_000.0
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    h = (
        math.sin(dphi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    )
    return radius_m * 2 * math.atan2(math.sqrt(h), math.sqrt(max(0.0, 1 - h)))
