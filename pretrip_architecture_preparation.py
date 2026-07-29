from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pretrip_reference_pace_energy_analysis import (
    DEFAULT_CHECKPOINTS_REF,
    DEFAULT_GEOJSON_REF,
    DEFAULT_MCP_CANDIDATES_REF,
    DEFAULT_MCP_NAMED_POINTS_REF,
    DEFAULT_REPORT_REF,
    DEFAULT_RISK_SCORE_POINTS_REF,
    DEFAULT_ROUTE_PRESSURE_PROFILE_REF,
    DEFAULT_SOURCE_INDEX_REF,
    write_reference_pace_energy_analysis,
)

ARTIFACT_KIND = "pretrip_architecture_preparation_manifest"
SCHEMA_VERSION = "architecture_preparation_manifest.v1"
DEFAULT_MANIFEST_REF = "outputs/architecture_preparation_manifest.json"

_PROJECT_OUTPUT_REFS = {
    "reference_pace_energy_analysis_ref": DEFAULT_REPORT_REF,
    "reference_pace_energy_map_geojson_ref": DEFAULT_GEOJSON_REF,
    "architecture_preparation_manifest_ref": DEFAULT_MANIFEST_REF,
}

_BOUNDARY = {
    "candidate_only": True,
    "medical_diagnosis": False,
    "phase1_runtime_mutation_allowed": False,
    "phase1_runtime_safety_truth": False,
    "runtime_safety_truth": False,
    "safety_api_called": False,
    "outbound_send_allowed": False,
    "hardware_control_allowed": False,
    "live_network_calls_made": False,
}

_PRIVACY = {
    "aggregate_only": True,
    "raw_gpx_embedded": False,
    "precise_timestamps_embedded": False,
    "source_original_paths_embedded": False,
}


def architecture_input_snapshot(
    project_root: Path | str,
    *,
    route_bin_m: float = 250.0,
    match_radius_m: float = 100.0,
    min_tracks_for_guidance: int = 3,
) -> dict[str, Any]:
    root = Path(project_root).expanduser().resolve()
    project = _load_json(root / "project.json")
    refs = {
        "historical_gpx_source_index": str(
            project.get("historical_gpx_source_index_ref")
            or DEFAULT_SOURCE_INDEX_REF
        ),
        "risk_score_points": str(
            project.get("risk_score_points_ref") or DEFAULT_RISK_SCORE_POINTS_REF
        ),
        "route_pressure_profile": str(
            project.get("route_pressure_profile_ref")
            or DEFAULT_ROUTE_PRESSURE_PROFILE_REF
        ),
        "checkpoint_candidates": str(
            project.get("checkpoint_candidates_ref") or DEFAULT_CHECKPOINTS_REF
        ),
        "mcp_candidates": str(
            project.get("mcp_candidates_ref") or DEFAULT_MCP_CANDIDATES_REF
        ),
        "mcp_named_point_evidence": str(
            project.get("mcp_named_point_evidence_ref")
            or DEFAULT_MCP_NAMED_POINTS_REF
        ),
    }
    source_paths: dict[str, Path] = {
        key: _resolve_ref(root, ref)
        for key, ref in refs.items()
    }
    for index, path in enumerate(
        sorted((root / "normalized/routes/filtered").glob("*.gpx"))
    ):
        source_paths[f"filtered_gpx_{index:04d}"] = path
    source_index = _load_optional_json(
        source_paths["historical_gpx_source_index"]
    )
    for index, source in enumerate(_list_value(source_index.get("sources"))):
        if not isinstance(source, dict):
            continue
        workspace_ref = source.get("workspace_ref")
        if not isinstance(workspace_ref, str) or not workspace_ref:
            continue
        source_path = _resolve_ref(root, workspace_ref).resolve()
        try:
            source_path.relative_to(root)
        except ValueError:
            continue
        source_paths[f"historical_gpx_{index:04d}"] = source_path

    files = []
    for key, path in sorted(source_paths.items()):
        relative_ref = _relative_ref(root, path)
        files.append(
            {
                "input_id": key,
                "source_path": relative_ref,
                "status": "available" if path.is_file() else "missing",
                "sha256": _sha256_file(path) if path.is_file() else None,
            }
        )
    policy = {
        "route_bin_m": float(route_bin_m),
        "match_radius_m": float(match_radius_m),
        "min_tracks_for_guidance": max(1, int(min_tracks_for_guidance)),
        "core_route_axis_policy": (
            "primary_speed_filtered_gpx_then_scope_reference_gpx"
        ),
        "enrichment_policy": "risk_and_route_pressure_are_optional_enrichments",
    }
    fingerprint_payload = {
        "project_id": str(project.get("project_id") or project.get("id") or root.name),
        "files": files,
        "policy": policy,
    }
    return {
        **fingerprint_payload,
        "input_sha256": _sha256_json(fingerprint_payload),
    }


def prepare_route_architecture_intelligence(
    project_root: Path | str,
    *,
    generated_at: str | None = None,
    force: bool = False,
    require_enriched: bool = False,
    route_bin_m: float = 250.0,
    match_radius_m: float = 100.0,
    min_tracks_for_guidance: int = 3,
) -> dict[str, Any]:
    root = Path(project_root).expanduser().resolve()
    project_path = root / "project.json"
    project = _load_json(project_path)
    project_id = str(project.get("project_id") or project.get("id") or root.name)
    prepared_at = generated_at or datetime.now(timezone.utc).isoformat()
    input_snapshot = architecture_input_snapshot(
        root,
        route_bin_m=route_bin_m,
        match_radius_m=match_radius_m,
        min_tracks_for_guidance=min_tracks_for_guidance,
    )
    manifest_path = root / DEFAULT_MANIFEST_REF
    report_path = root / DEFAULT_REPORT_REF
    map_path = root / DEFAULT_GEOJSON_REF
    existing = _load_optional_json(manifest_path)
    if (
        not force
        and existing.get("input_sha256") == input_snapshot["input_sha256"]
        and report_path.is_file()
        and map_path.is_file()
        and existing.get("status") in {"ready", "partial"}
    ):
        _update_project(
            project_path,
            project,
            manifest=existing,
            prepared_at=str(existing.get("generated_at") or prepared_at),
        )
        return _result_from_manifest(
            existing,
            reused=True,
            require_enriched=require_enriched,
        )

    try:
        analysis_result = write_reference_pace_energy_analysis(
            root,
            generated_at=prepared_at,
            route_bin_m=route_bin_m,
            match_radius_m=match_radius_m,
            min_tracks_for_guidance=min_tracks_for_guidance,
        )
        report = _load_json(report_path)
        pace_map = _load_json(map_path)
        counts = _dict_value(report.get("counts"))
        observed_bin_count = int(counts.get("observed_route_bin_count") or 0)
        map_feature_count = len(_list_value(pace_map.get("features")))
        browseable = (
            analysis_result.get("status") == "completed"
            and bool(observed_bin_count or map_feature_count)
        )
        preparation_stage = str(report.get("preparation_stage") or "core")
        status = (
            "ready"
            if browseable and preparation_stage == "enriched"
            else "partial"
            if analysis_result.get("status") == "completed"
            else "blocked"
        )
        error = None
    except (FileNotFoundError, ValueError, json.JSONDecodeError) as exc:
        report = {}
        counts = {}
        observed_bin_count = 0
        map_feature_count = 0
        browseable = False
        preparation_stage = "unavailable"
        status = "blocked"
        error = f"{type(exc).__name__}: {exc}"
    except Exception as exc:  # pragma: no cover - diagnostic fail-closed path
        report = {}
        counts = {}
        observed_bin_count = 0
        map_feature_count = 0
        browseable = False
        preparation_stage = "unavailable"
        status = "failed"
        error = f"{type(exc).__name__}: {exc}"

    manifest = {
        "artifact_kind": ARTIFACT_KIND,
        "schema_version": SCHEMA_VERSION,
        "project_id": project_id,
        "generated_at": prepared_at,
        "status": status,
        "preparation_stage": preparation_stage,
        "fresh": True,
        "browseable": browseable,
        "input_sha256": input_snapshot["input_sha256"],
        "inputs": input_snapshot,
        "output_refs": dict(_PROJECT_OUTPUT_REFS),
        "counts": {
            "observed_route_bin_count": observed_bin_count,
            "guidance_eligible_route_bin_count": int(
                counts.get("guidance_eligible_route_bin_count") or 0
            ),
            "checkpoint_passage_timing_node_count": int(
                counts.get("checkpoint_passage_timing_node_count") or 0
            ),
            "pace_map_feature_count": map_feature_count,
        },
        "data_quality": {
            "status": _dict_value(report.get("data_quality")).get(
                "status",
                "unavailable",
            ),
            "risk_enrichment_available": bool(
                _dict_value(report.get("data_quality")).get(
                    "risk_enrichment_available"
                )
            ),
            "terrain_enrichment_available": bool(
                _dict_value(report.get("data_quality")).get(
                    "terrain_enrichment_available"
                )
            ),
            "readiness_reason": _readiness_reason(
                status=status,
                preparation_stage=preparation_stage,
                browseable=browseable,
            ),
        },
        "error": error,
        "privacy": dict(_PRIVACY),
        "boundary": dict(_BOUNDARY),
    }
    _write_json(manifest_path, manifest)
    _update_project(
        project_path,
        project,
        manifest=manifest,
        prepared_at=prepared_at,
    )
    return _result_from_manifest(
        manifest,
        reused=False,
        require_enriched=require_enriched,
    )


def inspect_architecture_readiness(
    project_root: Path | str,
    *,
    route_bin_m: float = 250.0,
    match_radius_m: float = 100.0,
    min_tracks_for_guidance: int = 3,
) -> dict[str, Any]:
    root = Path(project_root).expanduser().resolve()
    manifest = _load_optional_json(root / DEFAULT_MANIFEST_REF)
    if not manifest:
        return {
            "status": "missing",
            "fresh": False,
            "browseable": False,
            "preparation_stage": "unavailable",
            "input_sha256": architecture_input_snapshot(
                root,
                route_bin_m=route_bin_m,
                match_radius_m=match_radius_m,
                min_tracks_for_guidance=min_tracks_for_guidance,
            )["input_sha256"],
            "manifest_input_sha256": None,
        }
    current = architecture_input_snapshot(
        root,
        route_bin_m=route_bin_m,
        match_radius_m=match_radius_m,
        min_tracks_for_guidance=min_tracks_for_guidance,
    )
    fresh = current["input_sha256"] == manifest.get("input_sha256")
    report_exists = (root / DEFAULT_REPORT_REF).is_file()
    map_exists = (root / DEFAULT_GEOJSON_REF).is_file()
    status = str(manifest.get("status") or "missing")
    if not fresh and report_exists and map_exists:
        status = "stale"
    elif not report_exists or not map_exists:
        status = "blocked"
    return {
        "status": status,
        "fresh": fresh,
        "browseable": bool(manifest.get("browseable") and report_exists and map_exists),
        "preparation_stage": str(
            manifest.get("preparation_stage") or "unavailable"
        ),
        "input_sha256": current["input_sha256"],
        "manifest_input_sha256": manifest.get("input_sha256"),
        "counts": _dict_value(manifest.get("counts")),
        "output_refs": _dict_value(manifest.get("output_refs")),
        "boundary": _dict_value(manifest.get("boundary")),
    }


def _result_from_manifest(
    manifest: dict[str, Any],
    *,
    reused: bool,
    require_enriched: bool,
) -> dict[str, Any]:
    counts = _dict_value(manifest.get("counts"))
    status = str(manifest.get("status") or "failed")
    return {
        "status": status,
        "preparation_stage": str(
            manifest.get("preparation_stage") or "unavailable"
        ),
        "reused": reused,
        "fresh": bool(manifest.get("fresh")),
        "browseable": bool(manifest.get("browseable")),
        "require_enriched": require_enriched,
        "requirement_satisfied": (
            status == "ready" if require_enriched else status in {"ready", "partial"}
        ),
        "input_sha256": manifest.get("input_sha256"),
        "observed_route_bin_count": int(
            counts.get("observed_route_bin_count") or 0
        ),
        "guidance_eligible_route_bin_count": int(
            counts.get("guidance_eligible_route_bin_count") or 0
        ),
        "checkpoint_passage_timing_node_count": int(
            counts.get("checkpoint_passage_timing_node_count") or 0
        ),
        "output_refs": _dict_value(manifest.get("output_refs")),
        "data_quality": _dict_value(manifest.get("data_quality")),
        "boundary": _dict_value(manifest.get("boundary")),
        "error": manifest.get("error"),
    }


def _update_project(
    project_path: Path,
    project: dict[str, Any],
    *,
    manifest: dict[str, Any],
    prepared_at: str,
) -> None:
    counts = _dict_value(manifest.get("counts"))
    updated = {
        **project,
        **_PROJECT_OUTPUT_REFS,
        "architecture_preparation_status": manifest.get("status"),
        "architecture_preparation_stage": manifest.get("preparation_stage"),
        "architecture_preparation_input_sha256": manifest.get("input_sha256"),
        "architecture_preparation_updated_at": prepared_at,
        "architecture_observed_route_bin_count": int(
            counts.get("observed_route_bin_count") or 0
        ),
        "architecture_guidance_eligible_route_bin_count": int(
            counts.get("guidance_eligible_route_bin_count") or 0
        ),
        "architecture_checkpoint_passage_timing_node_count": int(
            counts.get("checkpoint_passage_timing_node_count") or 0
        ),
    }
    _write_json(project_path, updated)


def _readiness_reason(
    *,
    status: str,
    preparation_stage: str,
    browseable: bool,
) -> str:
    if status == "ready":
        return "core_route_axis_and_optional_risk_terrain_enrichments_available"
    if browseable and preparation_stage == "core":
        return "core_route_axis_available_enrichments_pending"
    if status == "blocked":
        return "historical_source_index_or_route_axis_missing"
    return "architecture_preparation_failed"


def _resolve_ref(root: Path, ref: str) -> Path:
    path = Path(ref)
    return path if path.is_absolute() else root / path


def _relative_ref(root: Path, path: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def _load_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(path)
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def _load_optional_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sha256_json(payload: dict[str, Any]) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _dict_value(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _list_value(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Prepare candidate-only Route Architecture Intelligence artifacts "
            "and record deterministic readiness."
        )
    )
    parser.add_argument("--project-root", required=True, type=Path)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--require-enriched", action="store_true")
    parser.add_argument("--route-bin-m", type=float, default=250.0)
    parser.add_argument("--match-radius-m", type=float, default=100.0)
    parser.add_argument("--min-tracks-for-guidance", type=int, default=3)
    parser.add_argument("--generated-at")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    result = prepare_route_architecture_intelligence(
        args.project_root,
        generated_at=args.generated_at,
        force=args.force,
        require_enriched=args.require_enriched,
        route_bin_m=args.route_bin_m,
        match_radius_m=args.match_radius_m,
        min_tracks_for_guidance=args.min_tracks_for_guidance,
    )
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(
            "Route Architecture preparation: "
            f"{result['status']} ({result['preparation_stage']})"
        )
    return 0 if result["requirement_satisfied"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
