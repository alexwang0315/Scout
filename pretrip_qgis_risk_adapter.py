from __future__ import annotations

import bisect
import csv
import hashlib
import json
import math
import os
import shutil
import sys
from pathlib import Path
from typing import Any


QGIS_GRASS_RISK_OUTPUT_REFS = {
    "risk_route_profile_ref": "outputs/risk/route_risk.geojson",
    "risk_route_profile_csv_ref": "outputs/risk/route_risk.csv",
    "risk_route_profile_metadata_ref": "outputs/risk/route_risk.metadata.json",
    "risk_score_points_ref": "outputs/risk/risk_score_points.geojson",
    "risk_score_points_csv_ref": "outputs/risk/risk_score_points.csv",
    "risk_score_points_xyz_ref": "outputs/risk/risk_score_points.xyz",
    "risk_score_points_metadata_ref": "outputs/risk/risk_score_points.metadata.json",
    "risk_ribbon_ref": "outputs/risk/risk_ribbon.geojson",
    "risk_ribbon_metadata_ref": "outputs/risk/risk_ribbon.metadata.json",
}

QGIS_RISK_ADAPTER_ID = "scout_qgis_grass_risk_profile_adapter.v1"
QGIS_RISK_SCORE_PROFILE_ID = "qgis_grass_terrain_candidate_score.v1"
TERRAIN_WORKFLOW_ID = "terrain_feature_stack.v1"
ROUTE_BASE_INTERVAL_M = 20.0
RISK_RIBBON_MAX_SEGMENT_M = 80.0
_MAX_QGIS_SAMPLES = 20_000
_RISK_THRESHOLDS = (20.0, 40.0, 60.0, 80.0)
_SCORE_WEIGHTS = {
    "slope": 0.70,
    "geomorphon": 0.20,
    "flow_accumulation": 0.10,
}
_GEOMORPHON_PRESSURE = {
    "flat": 0.0,
    "peak": 55.0,
    "ridge": 60.0,
    "shoulder": 45.0,
    "spur": 55.0,
    "slope": 50.0,
    "hollow": 65.0,
    "footslope": 35.0,
    "valley": 65.0,
    "pit": 45.0,
}


class QgisGrassRiskAdapterError(ValueError):
    pass


def prepare_qgis_grass_risk_outputs(
    *,
    project_root: Path,
    project_id: str,
    qgis_workflow_run_id: str,
    overpass_geojson_path: Path,
    reference_gpx_path: Path,
    prepared_at: str,
    route_corridor_m: float,
) -> dict[str, Any]:
    """Adapt verified QGIS/GRASS samples into candidate-only risk artifacts.

    This function never reads or analyzes a DEM. It applies a versioned contract
    score to terrain values already sampled by QGIS and packages those values on
    the existing Overpass route-base geometry without adding source resolution.
    """

    root = Path(project_root).expanduser().resolve()
    if not root.is_dir():
        raise QgisGrassRiskAdapterError("project workspace is unavailable")
    if not qgis_workflow_run_id or Path(qgis_workflow_run_id).name != qgis_workflow_run_id:
        raise QgisGrassRiskAdapterError("QGIS workflow run id is unsafe")
    if not math.isfinite(float(route_corridor_m)) or route_corridor_m <= 0:
        raise QgisGrassRiskAdapterError("route corridor must be positive")

    qgis_context = _verified_qgis_route_samples(
        project_root=root,
        workflow_run_id=qgis_workflow_run_id,
    )
    qgis_samples = qgis_context["samples"]
    _ensure_scout_risk_package_importable()
    from scout_risk.overpass.route_base import build_overpass_route_base
    from scout_risk.route.risk_score_map import (
        build_risk_ribbon_from_geojson,
        build_risk_score_point_map_from_geojson,
        write_risk_ribbon_geojson,
        write_risk_ribbon_metadata,
        write_risk_score_csv,
        write_risk_score_geojson,
        write_risk_score_metadata,
        write_risk_score_xyz,
    )

    route_base = build_overpass_route_base(
        overpass_geojson_path=overpass_geojson_path,
        reference_gpx_path=reference_gpx_path,
        route_id=f"{project_id}.qgis_grass_candidate",
        corridor_m=float(route_corridor_m),
        reference_interval_m=ROUTE_BASE_INTERVAL_M,
    )
    route_features = _build_route_risk_features(
        project_id=project_id,
        route_base=route_base,
        qgis_samples=qgis_samples,
        qgis_workflow_run_id=qgis_workflow_run_id,
    )
    if len(route_features) < 2:
        raise QgisGrassRiskAdapterError(
            "QGIS/GRASS route-risk adapter produced fewer than two route samples"
        )

    route_metadata = _route_risk_metadata(
        prepared_at=prepared_at,
        qgis_context=qgis_context,
        route_base_metadata=route_base.metadata,
        route_feature_count=len(route_features),
        overpass_geojson_path=Path(overpass_geojson_path),
        reference_gpx_path=Path(reference_gpx_path),
        route_corridor_m=float(route_corridor_m),
    )
    route_payload = {
        "type": "FeatureCollection",
        "metadata": route_metadata,
        "features": route_features,
    }

    risk_root = root / "outputs/risk"
    temporary_root = risk_root / (
        f".qgis-risk-adapter-{os.getpid()}-{qgis_workflow_run_id}"
    )
    temporary_root.mkdir(parents=True, exist_ok=False)
    try:
        route_path = temporary_root / "route_risk.geojson"
        _write_json(route_path, route_payload)
        _write_json(temporary_root / "route_risk.metadata.json", route_metadata)
        _write_route_risk_csv(
            temporary_root / "route_risk.csv",
            route_features,
        )

        point_map = build_risk_score_point_map_from_geojson(route_path)
        ribbon = build_risk_ribbon_from_geojson(
            route_path,
            max_route_base_segment_m=RISK_RIBBON_MAX_SEGMENT_M,
        )
        common_metadata = {
            "actual_processor": "qgis_processing_grass",
            "adapter": QGIS_RISK_ADAPTER_ID,
            "score_profile_id": QGIS_RISK_SCORE_PROFILE_ID,
            "source_qgis_route_samples_ref": qgis_context["samples_ref"],
            "source_qgis_route_samples_sha256": qgis_context["samples_sha256"],
            "workflow_id": TERRAIN_WORKFLOW_ID,
            "workflow_run_id": qgis_workflow_run_id,
            "fallback_used": False,
            "python_dtm_processing_used": False,
            "candidate_only": True,
            "runtime_safety_truth": False,
            "operational": False,
            "adds_source_resolution": False,
        }
        point_map.metadata.update(common_metadata)
        point_map.metadata["source_route_risk_ref"] = (
            QGIS_GRASS_RISK_OUTPUT_REFS["risk_route_profile_ref"]
        )
        ribbon.metadata.update(common_metadata)
        ribbon.metadata["source_route_risk_ref"] = (
            QGIS_GRASS_RISK_OUTPUT_REFS["risk_route_profile_ref"]
        )
        write_risk_score_geojson(
            point_map,
            temporary_root / "risk_score_points.geojson",
        )
        write_risk_score_csv(point_map, temporary_root / "risk_score_points.csv")
        write_risk_score_xyz(point_map, temporary_root / "risk_score_points.xyz")
        write_risk_score_metadata(
            point_map,
            temporary_root / "risk_score_points.metadata.json",
        )
        write_risk_ribbon_geojson(ribbon, temporary_root / "risk_ribbon.geojson")
        write_risk_ribbon_metadata(
            ribbon,
            temporary_root / "risk_ribbon.metadata.json",
        )
        _publish_outputs(root, temporary_root)
    except Exception:
        shutil.rmtree(temporary_root, ignore_errors=True)
        raise
    else:
        shutil.rmtree(temporary_root, ignore_errors=True)

    return {
        "status": "completed",
        "actual_processor": "qgis_processing_grass",
        "adapter": QGIS_RISK_ADAPTER_ID,
        "score_profile_id": QGIS_RISK_SCORE_PROFILE_ID,
        "fallback_used": False,
        "python_dtm_processing_used": False,
        "candidate_only": True,
        "runtime_safety_truth": False,
        "operational": False,
        "adds_source_resolution": False,
        "counts": {
            "qgis_source_sample_count": len(qgis_samples),
            "route_risk_sample_count": len(route_features),
            "risk_score_point_count": len(point_map.points),
            "risk_ribbon_segment_count": len(ribbon.features),
        },
        "output_refs": dict(QGIS_GRASS_RISK_OUTPUT_REFS),
    }


def _verified_qgis_route_samples(
    *,
    project_root: Path,
    workflow_run_id: str,
) -> dict[str, Any]:
    run_ref = f"outputs/spatial/qgis/{workflow_run_id}/workflow_run.json"
    run_path = _safe_project_path(project_root, run_ref)
    run = _load_json(run_path, "QGIS workflow receipt")
    if any(
        (
            run.get("workflow_id") != TERRAIN_WORKFLOW_ID,
            run.get("workflow_run_id") != workflow_run_id,
            run.get("state") != "completed",
            run.get("candidate_only") is not True,
            run.get("runtime_safety_truth") is not False,
            run.get("operational") is not False,
        )
    ):
        raise QgisGrassRiskAdapterError("QGIS workflow receipt is not eligible")
    artifact = next(
        (
            item
            for item in run.get("artifacts", [])
            if isinstance(item, dict)
            and item.get("artifact_type") == "terrain_feature_route_samples"
        ),
        None,
    )
    if artifact is None:
        raise QgisGrassRiskAdapterError("QGIS terrain route samples are unavailable")
    if any(
        (
            artifact.get("fixture") is not False,
            artifact.get("synthetic") is not False,
            artifact.get("candidate_only") is not True,
            artifact.get("runtime_safety_truth") is not False,
            artifact.get("operational") is not False,
        )
    ):
        raise QgisGrassRiskAdapterError(
            "QGIS terrain route samples are fixture or synthetic evidence"
        )
    samples_ref = artifact.get("artifact_ref")
    expected_hash = artifact.get("artifact_hash")
    if not isinstance(samples_ref, str) or not isinstance(expected_hash, str):
        raise QgisGrassRiskAdapterError("QGIS terrain sample receipt is incomplete")
    samples_path = _safe_project_path(project_root, samples_ref)
    actual_hash = _sha256_file(samples_path)
    if actual_hash != expected_hash:
        raise QgisGrassRiskAdapterError("QGIS terrain route sample hash mismatch")
    payload = _load_json(samples_path, "QGIS terrain route samples")
    metadata = payload.get("metadata")
    features = payload.get("features")
    if (
        payload.get("type") != "FeatureCollection"
        or not isinstance(metadata, dict)
        or not isinstance(features, list)
        or not 1 <= len(features) <= _MAX_QGIS_SAMPLES
        or metadata.get("workflow_id") != TERRAIN_WORKFLOW_ID
        or metadata.get("workflow_run_id") != workflow_run_id
        or metadata.get("actual_processor") != "qgis_processing_grass"
        or metadata.get("candidate_only") is not True
        or metadata.get("runtime_safety_truth") is not False
        or metadata.get("operational") is not False
        or metadata.get("risk_score_applied") is not False
        or metadata.get("fixture") is not False
        or metadata.get("synthetic") is not False
    ):
        raise QgisGrassRiskAdapterError("QGIS terrain sample contract is invalid")
    samples = [_validated_qgis_sample(feature) for feature in features]
    samples.sort(key=lambda sample: sample["distance_m"])
    return {
        "run_ref": run_ref,
        "run_sha256": _sha256_file(run_path),
        "samples_ref": samples_ref,
        "samples_sha256": actual_hash,
        "samples": samples,
    }


def _validated_qgis_sample(feature: Any) -> dict[str, Any]:
    if not isinstance(feature, dict):
        raise QgisGrassRiskAdapterError("QGIS terrain sample is malformed")
    geometry = feature.get("geometry")
    properties = feature.get("properties")
    coordinates = geometry.get("coordinates") if isinstance(geometry, dict) else None
    if (
        not isinstance(geometry, dict)
        or geometry.get("type") != "Point"
        or not isinstance(coordinates, list)
        or len(coordinates) < 2
        or not isinstance(properties, dict)
        or properties.get("candidate_only") is not True
        or properties.get("runtime_safety_truth") is not False
        or properties.get("operational") is not False
        or properties.get("risk_score_applied") is not False
        or properties.get("fixture") is not False
        or properties.get("synthetic") is not False
    ):
        raise QgisGrassRiskAdapterError("QGIS terrain sample authority is invalid")
    lon = _finite_float(coordinates[0])
    lat = _finite_float(coordinates[1])
    distance_m = _finite_float(properties.get("distance_m"))
    slope_degrees = _finite_float(properties.get("slope_degrees"))
    if (
        lon is None
        or lat is None
        or distance_m is None
        or distance_m < 0
        or slope_degrees is None
        or not -180 <= lon <= 180
        or not -90 <= lat <= 90
    ):
        raise QgisGrassRiskAdapterError(
            "QGIS terrain sample is missing route distance, coordinate, or slope"
        )
    return {
        "lon": lon,
        "lat": lat,
        "distance_m": distance_m,
        "properties": dict(properties),
    }


def _build_route_risk_features(
    *,
    project_id: str,
    route_base: Any,
    qgis_samples: list[dict[str, Any]],
    qgis_workflow_run_id: str,
) -> list[dict[str, Any]]:
    distances = [sample["distance_m"] for sample in qgis_samples]
    features: list[dict[str, Any]] = []
    for index, (point, route_metadata) in enumerate(
        zip(route_base.points, route_base.sample_metadata)
    ):
        route_distance_m = _finite_float(route_metadata.get("reference_distance_m"))
        if route_distance_m is None:
            continue
        sample = _nearest_distance_sample(
            qgis_samples,
            distances=distances,
            target=route_distance_m,
        )
        source = sample["properties"]
        score = _candidate_score(source)
        sample_id = f"{project_id}.qgis-grass-risk.{index:05d}"
        qgis_sample_distance = sample["distance_m"]
        properties = {
            "route_id": route_base.route_id,
            "sample_id": sample_id,
            "distance_m": round(route_distance_m, 2),
            "elevation_m": _finite_float(source.get("elevation_m")),
            "teii_20m": None,
            "tri": None,
            "sri": None,
            "lec": None,
            "scp": 0.0,
            "pretrip_risk": score["score"],
            "risk_level": _risk_level(score["score"]),
            "hazard_types": [],
            "explanation": [
                "Candidate score is adapted from QGIS/GRASS terrain samples; field verification is required."
            ],
            "route_base_source": route_metadata.get("route_base_source"),
            "route_base_feature_id": route_metadata.get("route_base_feature_id"),
            "route_base_projection_distance_m": route_metadata.get(
                "route_base_projection_distance_m"
            ),
            "qgis_sample_id": source.get("sample_id"),
            "qgis_sample_distance_m": round(qgis_sample_distance, 2),
            "qgis_sample_distance_delta_m": round(
                abs(route_distance_m - qgis_sample_distance), 2
            ),
            "qgis_workflow_run_id": qgis_workflow_run_id,
            "slope_degrees": _finite_float(source.get("slope_degrees")),
            "aspect_degrees": _finite_float(source.get("aspect_degrees")),
            "geomorphon_label": score["geomorphon_label"],
            "flow_accumulation_abs_cells": _finite_float(
                source.get("flow_accumulation_abs_cells")
            ),
            "score_profile_id": QGIS_RISK_SCORE_PROFILE_ID,
            "score_components": score["components"],
            "actual_processor": "qgis_processing_grass",
            "adapter": QGIS_RISK_ADAPTER_ID,
            "candidate_only": True,
            "runtime_safety_truth": False,
            "operational": False,
            "risk_score_applied": True,
            "fallback_used": False,
            "python_dtm_processing_used": False,
            "adds_source_resolution": False,
        }
        features.append(
            {
                "type": "Feature",
                "geometry": {
                    "type": "Point",
                    "coordinates": [float(point.lon), float(point.lat)],
                },
                "properties": properties,
            }
        )
    return features


def _candidate_score(properties: dict[str, Any]) -> dict[str, Any]:
    slope = abs(float(properties["slope_degrees"]))
    slope_pressure = _clamp(slope / 45.0 * 100.0)
    geomorphon_label = str(
        properties.get("geomorphon_consensus_label")
        or properties.get("geomorphon_label")
        or ""
    ).lower()
    geomorphon_pressure = _GEOMORPHON_PRESSURE.get(geomorphon_label)
    flow = _finite_float(properties.get("flow_accumulation_abs_cells"))
    if flow is None:
        raw_flow = _finite_float(properties.get("flow_accumulation_cells"))
        flow = abs(raw_flow) if raw_flow is not None else None
    flow_pressure = (
        _clamp(math.log10(1.0 + max(0.0, flow)) / 4.0 * 100.0)
        if flow is not None
        else None
    )
    values = {
        "slope": slope_pressure,
        "geomorphon": geomorphon_pressure,
        "flow_accumulation": flow_pressure,
    }
    available_weight = sum(
        _SCORE_WEIGHTS[key] for key, value in values.items() if value is not None
    )
    score = sum(
        _SCORE_WEIGHTS[key] * float(value)
        for key, value in values.items()
        if value is not None
    ) / available_weight
    return {
        "score": round(_clamp(score), 2),
        "geomorphon_label": geomorphon_label or None,
        "components": {
            key: round(value, 2) if value is not None else None
            for key, value in values.items()
        },
    }


def _route_risk_metadata(
    *,
    prepared_at: str,
    qgis_context: dict[str, Any],
    route_base_metadata: dict[str, Any],
    route_feature_count: int,
    overpass_geojson_path: Path,
    reference_gpx_path: Path,
    route_corridor_m: float,
) -> dict[str, Any]:
    score_profile = {
        "profile_id": QGIS_RISK_SCORE_PROFILE_ID,
        "adapter": QGIS_RISK_ADAPTER_ID,
        "inputs": [
            "slope_degrees",
            "geomorphon_consensus_label_or_geomorphon_label",
            "flow_accumulation_abs_cells",
        ],
        "weights": dict(_SCORE_WEIGHTS),
        "slope_scale_degrees": 45.0,
        "flow_transform": "log10(1 + absolute_cells) scaled to 0-100 at 10000 cells",
        "geomorphon_pressure": dict(_GEOMORPHON_PRESSURE),
        "missing_component_policy": "renormalize_available_weights; slope_required",
        "risk_level_thresholds": list(_RISK_THRESHOLDS),
        "visualization_packaging_only": False,
        "validated_operational_risk_model": False,
        "adds_source_resolution": False,
    }
    return {
        "artifact_kind": "scout_qgis_grass_route_risk_profile_metadata",
        "schema_version": "scout_qgis_grass_route_risk_profile.v1",
        "generated_at": prepared_at,
        "actual_processor": "qgis_processing_grass",
        "adapter": QGIS_RISK_ADAPTER_ID,
        "workflow_id": TERRAIN_WORKFLOW_ID,
        "workflow_run_id": qgis_context["samples"][0]["properties"].get(
            "workflow_run_id"
        )
        or Path(qgis_context["run_ref"]).parent.name,
        "source_qgis_workflow_run_ref": qgis_context["run_ref"],
        "source_qgis_workflow_run_sha256": qgis_context["run_sha256"],
        "source_qgis_route_samples_ref": qgis_context["samples_ref"],
        "source_qgis_route_samples_sha256": qgis_context["samples_sha256"],
        "source_qgis_route_sample_count": len(qgis_context["samples"]),
        "source_overpass_ref": str(overpass_geojson_path),
        "source_overpass_sha256": _sha256_file(overpass_geojson_path),
        "source_reference_gpx_ref": str(reference_gpx_path),
        "source_reference_gpx_sha256": _sha256_file(reference_gpx_path),
        "route_risk_sample_count": route_feature_count,
        "route_base": route_base_metadata,
        "route_preparation": {
            "corridor_m": route_corridor_m,
            "reference_interval_m": ROUTE_BASE_INTERVAL_M,
            "qgis_value_packaging": (
                "nearest_qgis_route_sample_by_reference_progress"
            ),
            "qgis_values_interpolated": False,
            "route_geometry_added_source_resolution": False,
        },
        "score_profile": score_profile,
        "fallback_used": False,
        "python_dtm_processing_used": False,
        "warnings": [
            "The score is candidate-only pretrip evidence derived from QGIS/GRASS terrain samples.",
            "Repeated nearest-sample values package sparse QGIS evidence on route-base geometry and do not add terrain resolution.",
            "Processing success does not establish hazard, route, navigability, or safety truth.",
        ],
        "boundary": {
            "candidate_only": True,
            "runtime_safety_truth": False,
            "operational": False,
            "adds_source_resolution": False,
            "python_dtm_processing_used": False,
            "fallback_used": False,
        },
    }


def _publish_outputs(project_root: Path, temporary_root: Path) -> None:
    for ref in QGIS_GRASS_RISK_OUTPUT_REFS.values():
        filename = Path(ref).name
        source = temporary_root / filename
        if not source.is_file():
            raise QgisGrassRiskAdapterError(
                f"QGIS/GRASS risk adapter omitted output: {filename}"
            )
    for ref in QGIS_GRASS_RISK_OUTPUT_REFS.values():
        destination = _safe_project_path(project_root, ref, require_exists=False)
        destination.parent.mkdir(parents=True, exist_ok=True)
        (temporary_root / Path(ref).name).replace(destination)


def _write_route_risk_csv(path: Path, features: list[dict[str, Any]]) -> None:
    fields = [
        "route_id",
        "sample_id",
        "distance_m",
        "lat",
        "lon",
        "elevation_m",
        "pretrip_risk",
        "risk_level",
        "route_base_source",
        "route_base_feature_id",
        "route_base_projection_distance_m",
        "qgis_sample_id",
        "qgis_sample_distance_m",
        "qgis_sample_distance_delta_m",
        "slope_degrees",
        "aspect_degrees",
        "geomorphon_label",
        "flow_accumulation_abs_cells",
        "score_profile_id",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for feature in features:
            properties = dict(feature["properties"])
            lon, lat = feature["geometry"]["coordinates"][:2]
            properties.update({"lat": lat, "lon": lon})
            writer.writerow({field: properties.get(field) for field in fields})


def _nearest_distance_sample(
    samples: list[dict[str, Any]],
    *,
    distances: list[float],
    target: float,
) -> dict[str, Any]:
    index = bisect.bisect_left(distances, target)
    candidates = samples[max(0, index - 1) : min(len(samples), index + 1)]
    return min(candidates, key=lambda sample: abs(sample["distance_m"] - target))


def _risk_level(score: float) -> int:
    for index, threshold in enumerate(_RISK_THRESHOLDS, start=1):
        if score < threshold:
            return index
    return 5


def _safe_project_path(
    project_root: Path,
    ref: str,
    *,
    require_exists: bool = True,
) -> Path:
    relative = Path(ref)
    if relative.is_absolute() or ".." in relative.parts:
        raise QgisGrassRiskAdapterError("artifact ref escapes the workspace")
    path = (project_root / relative).resolve()
    try:
        path.relative_to(project_root)
    except ValueError as exc:
        raise QgisGrassRiskAdapterError("artifact ref escapes the workspace") from exc
    if require_exists and not path.is_file():
        raise QgisGrassRiskAdapterError(f"artifact is unavailable: {ref}")
    return path


def _load_json(path: Path, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise QgisGrassRiskAdapterError(f"{label} is unavailable or malformed") from exc
    if not isinstance(payload, dict):
        raise QgisGrassRiskAdapterError(f"{label} must be an object")
    return payload


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as exc:
        raise QgisGrassRiskAdapterError(f"source artifact is unavailable: {path}") from exc
    return digest.hexdigest()


def _finite_float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _clamp(value: float) -> float:
    return max(0.0, min(100.0, float(value)))


def _ensure_scout_risk_package_importable() -> None:
    package_src = (
        Path(__file__).resolve().parent
        / "scout-risk-engine"
        / "scout_codex_package"
        / "src"
    )
    if not package_src.is_dir():
        raise QgisGrassRiskAdapterError("Scout risk contract package is unavailable")
    source = package_src.as_posix()
    if source not in sys.path:
        sys.path.insert(0, source)
