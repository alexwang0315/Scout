from __future__ import annotations

import hashlib
import importlib.util
import ipaddress
import json
import os
import re
import tempfile
from dataclasses import dataclass, fields
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Literal
from urllib.parse import urlparse

from pretrip_import import PretripImportRequest, run_pretrip_import
from dashboard_workspace_preparation import (
    PREPARATION_OPTION_FIELDS,
    build_workspace_preparation_request,
    resolve_workspace_preparation_inputs,
)
from pretrip_layer_preparation import (
    DEFAULT_LAYERS,
    LayerPreparationRequest,
    run_layer_preparation,
)
from pretrip_mcp_synthesis import load_named_point_evidence
from pretrip_models import DtmRasterSource
from pretrip_source_ingest import sha256_file


PROJECT_ID_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+$")
WORKSPACE_CLONE_RECEIPT_REF = Path("outputs/workspace_clone_receipt.json")
ROUTE_CONTEXT_SOURCE_HANDOFF_REF = Path("inputs/route_context_source_records.json")
ROUTE_CONTEXT_SOURCE_HANDOFF_KIND = (
    "dashboard_workspace_route_context_source_handoff"
)

ImportRunner = Callable[[PretripImportRequest], dict[str, Any]]
PreparationRunner = Callable[[LayerPreparationRequest], dict[str, Any]]


class WorkspaceClonePreparationError(RuntimeError):
    pass


@dataclass(frozen=True)
class WorkspaceCloneRequest:
    source_project_id: str
    target_project_id: str
    source_project_root: Path
    workspace_root: Path
    layers: tuple[str, ...] = DEFAULT_LAYERS
    profile: Literal["mac-workstation", "pi-offline", "pi-online-explicit"] = (
        "mac-workstation"
    )
    network_mode: Literal["no-network", "explicit-fetch"] = "explicit-fetch"
    allow_network_fetch: bool = True
    prepare_cwa_imagery: bool = True
    route_corridor_m: float = 500.0
    reference_track_corridor_m: float = 300.0
    seed_imagery_cache: bool = True
    imagery_min_zoom: int = 5
    imagery_max_zoom: int = 14
    imagery_provider_allows_offline_prefetch: bool = True
    imagery_seed_max_tiles: int | None = None
    osmium_bin: str = "osmium"
    requested_by: str = "dashboard_operator"


def clone_pretrip_workspace_from_inputs(
    request: WorkspaceCloneRequest,
    *,
    import_runner: ImportRunner = run_pretrip_import,
    preparation_runner: PreparationRunner = run_layer_preparation,
) -> dict[str, Any]:
    source_root, workspace_root, target_root = _validated_roots(request)
    source_project = _load_json_object(source_root / "project.json")
    if source_project.get("project_id") != request.source_project_id:
        raise ValueError("source workspace project_id does not match requested project")

    source_manifest = _load_json_object(source_root / "inbox" / "source_manifest.json")
    if source_manifest.get("project_id") != request.source_project_id:
        raise ValueError("source inbox manifest project_id does not match source workspace")
    primary_gpx, reference_gpx, source_records = _source_gpx_inputs(
        source_root,
        source_manifest,
    )
    route_context_source_handoff = _route_context_source_handoff_payload(
        source_root=source_root,
        source_project=source_project,
        source_project_id=request.source_project_id,
        target_project_id=request.target_project_id,
    )
    preparation_inputs = resolve_workspace_preparation_inputs(source_root)
    material_root = preparation_inputs.material_root
    material_manifest = preparation_inputs.material_manifest
    material_sources = material_manifest.get("sources", {})
    if not isinstance(material_sources, dict):
        material_sources = {}
    local_osm_pbf = preparation_inputs.local_osm_pbf or {}
    configured_osm_pbf_path = _existing_file(local_osm_pbf.get("path"))
    osm_pbf_path, osm_input_policy = _select_osm_preparation_input(
        configured_path=configured_osm_pbf_path,
        configured_sha256=_optional_text(local_osm_pbf.get("sha256")),
        osmium_bin=request.osmium_bin,
        allow_network_fetch=request.allow_network_fetch,
        network_mode=request.network_mode,
    )
    if configured_osm_pbf_path is not None and osm_pbf_path is None:
        raise WorkspaceClonePreparationError(
            "Local OSM PBF is configured but Python osmium is unavailable in "
            "the active Dashboard runtime. Run "
            "tools/setup_dashboard_workspace_runtime.sh once and start the "
            "Dashboard with tools/run_dashboard_workspace.sh; the target "
            "workspace was not created."
        )
    osm_pbf_source_url = _optional_text(local_osm_pbf.get("source_url"))
    osm_pbf_cache_ttl_days = _positive_int(
        local_osm_pbf.get("cache_ttl_days"),
        default=30,
    )
    reference_gpx, source_records, reference_discovery = (
        _discover_declared_material_reference_gpx(
            material_sources=material_sources,
            primary_gpx=primary_gpx,
            reference_gpx=reference_gpx,
            source_records=source_records,
        )
    )
    dtm_dirs = preparation_inputs.dtm_dirs
    mcp_source_evidence = _existing_file(
        material_sources.get("mcp_named_point_evidence")
    )
    mcp_named_point_evidence, mcp_rebinding = _rebound_mcp_evidence_input(
        source_path=mcp_source_evidence,
        source_project_id=request.source_project_id,
        target_project_id=request.target_project_id,
        workspace_root=workspace_root,
    )

    imported_at = _utc_now()
    try:
        import_manifest = import_runner(
            PretripImportRequest(
                project_id=request.target_project_id,
                primary_gpx=primary_gpx,
                reference_gpx_paths=reference_gpx,
                workspace_root=workspace_root,
                profile=request.profile,
                checkpoint_spacing_m=500.0,
                max_reference_display_points=1_000,
                max_reasonable_gpx_speed_kmh=120.0,
                max_previous_gpx_speed_ratio=8.0,
                material_root=material_root,
                resolve_default_material_root=False,
                dtm_dirs=dtm_dirs,
                dtm_raster_sources=tuple(
                    DtmRasterSource.model_validate(source)
                    for source in preparation_inputs.dtm_rasters
                ),
                mcp_named_point_evidence=mcp_named_point_evidence,
                overwrite=False,
                import_timestamp=imported_at,
                import_stage="pretrip",
            )
        )
    finally:
        if mcp_named_point_evidence is not None:
            mcp_named_point_evidence.unlink(missing_ok=True)

    route_context_source_handoff_summary = _write_route_context_source_handoff(
        target_root=target_root,
        payload=route_context_source_handoff,
    )

    try:
        preparation_options = {
            field.name: getattr(request, field.name)
            for field in fields(request)
            if field.name in PREPARATION_OPTION_FIELDS
        }
        preparation_options.update({
            "osm_pbf_path": osm_pbf_path,
            "osm_pbf_source_url": osm_pbf_source_url,
            "osm_pbf_cache_ttl_days": osm_pbf_cache_ttl_days,
        })
        preparation_manifest = preparation_runner(build_workspace_preparation_request(
            target_root,
            source_project_id=request.source_project_id,
            requested_by=request.requested_by,
            preparation_options=preparation_options,
        ))
    except Exception as exc:
        safe_error = (
            f"{type(exc).__name__}: map preparation failed; "
            "the target remains as an import-complete workspace"
        )
        if target_root.is_dir():
            _write_clone_receipt(
                target_root,
                _clone_receipt(
                    request=request,
                    status="imported_preparation_failed",
                    source_records=source_records,
                    import_manifest=import_manifest,
                    preparation_manifest=None,
                    material_root=material_root,
                    reference_discovery=reference_discovery,
                    mcp_rebinding=mcp_rebinding,
                    osm_input_policy=osm_input_policy,
                    route_context_source_handoff=(
                        route_context_source_handoff_summary
                    ),
                    error=safe_error,
                ),
            )
        raise WorkspaceClonePreparationError(safe_error) from exc

    qgis_terrain_stage = _qgis_terrain_stage(preparation_manifest)
    completion_status = _clone_completion_status(
        preparation_manifest,
        qgis_terrain_stage=qgis_terrain_stage,
    )
    receipt = _clone_receipt(
        request=request,
        status=completion_status,
        source_records=source_records,
        import_manifest=import_manifest,
        preparation_manifest=preparation_manifest,
        material_root=material_root,
        reference_discovery=reference_discovery,
        mcp_rebinding=mcp_rebinding,
        osm_input_policy=osm_input_policy,
        route_context_source_handoff=route_context_source_handoff_summary,
    )
    _write_clone_receipt(target_root, receipt)
    return {
        "source_project_id": request.source_project_id,
        "target_project_id": request.target_project_id,
        "project_root": str(target_root),
        "status": completion_status,
        "receipt": receipt,
        "import": {
            "status": "completed",
            "counts": import_manifest.get("counts", {}),
            "manifest_ref": import_manifest.get("outputs", {}).get(
                "import_manifest_ref"
            ),
        },
        "map_preparation": {
            "status": preparation_manifest.get("validation", {}).get(
                "status", "completed"
            ),
            "normalized_layers": preparation_manifest.get("normalized_layers", []),
            "counts": preparation_manifest.get("counts", {}),
            "manifest_ref": preparation_manifest.get("outputs", {}).get(
                "layer_preparation_manifest_ref"
            ),
            "qgis_terrain_feature_stack": qgis_terrain_stage,
            "terrain_status": qgis_terrain_stage.get("status"),
        },
        "boundary": receipt["boundary"],
    }


def _validated_roots(
    request: WorkspaceCloneRequest,
) -> tuple[Path, Path, Path]:
    for label, project_id in (
        ("source", request.source_project_id),
        ("target", request.target_project_id),
    ):
        if not PROJECT_ID_PATTERN.fullmatch(project_id):
            raise ValueError(f"invalid {label} project id: {project_id}")
    if request.source_project_id == request.target_project_id:
        raise ValueError("clone target must differ from source project")

    workspace_root = request.workspace_root.expanduser().resolve()
    source_root = request.source_project_root.expanduser().resolve()
    if source_root.parent != workspace_root:
        raise ValueError("source workspace must be a direct child of workspace root")
    target_root = (workspace_root / request.target_project_id).resolve()
    if target_root.parent != workspace_root:
        raise ValueError("clone target must remain inside workspace root")
    if target_root.exists():
        raise FileExistsError(f"clone target already exists: {target_root}")
    return source_root, workspace_root, target_root


def _source_gpx_inputs(
    source_root: Path,
    source_manifest: dict[str, Any],
) -> tuple[Path, tuple[Path, ...], list[dict[str, Any]]]:
    sources = source_manifest.get("sources")
    if not isinstance(sources, list):
        raise ValueError("source inbox manifest has no sources list")
    records: list[tuple[dict[str, Any], Path]] = []
    for source in sources:
        if not isinstance(source, dict):
            continue
        workspace_ref = source.get("workspace_ref")
        if not isinstance(workspace_ref, str) or not workspace_ref:
            continue
        path = (source_root / workspace_ref).resolve()
        if source_root not in path.parents or not path.is_file():
            raise ValueError(f"source GPX ref is missing or outside workspace: {workspace_ref}")
        expected_sha = _optional_text(source.get("sha256"))
        actual_sha = sha256_file(path)
        if expected_sha and actual_sha != expected_sha:
            raise ValueError(f"source GPX checksum mismatch: {workspace_ref}")
        records.append((source, path))

    primary = [path for source, path in records if source.get("role") == "golden_route_reference"]
    references = [path for source, path in records if source.get("role") == "reference_track"]
    if len(primary) != 1:
        raise ValueError("source workspace must contain exactly one golden route GPX")
    if not references:
        raise ValueError("source workspace must contain at least one reference GPX")
    receipt_records = [
        {
            "role": source.get("role"),
            "source_ref": str(path.relative_to(source_root)),
            "sha256": sha256_file(path),
            "size_bytes": path.stat().st_size,
        }
        for source, path in records
    ]
    return primary[0], tuple(references), receipt_records


def _discover_declared_material_reference_gpx(
    *,
    material_sources: dict[str, Any],
    primary_gpx: Path,
    reference_gpx: tuple[Path, ...],
    source_records: list[dict[str, Any]],
) -> tuple[tuple[Path, ...], list[dict[str, Any]], dict[str, Any]]:
    (
        reference_gpx,
        source_records,
        duplicate_existing_reference_count,
    ) = _deduplicate_existing_reference_gpx(
        primary_gpx=primary_gpx,
        reference_gpx=reference_gpx,
        source_records=source_records,
    )
    corpus_value = material_sources.get("gpx_corpus")
    if isinstance(corpus_value, dict):
        corpus_value = corpus_value.get("path")
    if not isinstance(corpus_value, str) or not corpus_value.strip():
        return reference_gpx, list(source_records), {
            "status": "not_declared",
            "additional_reference_count": 0,
            "duplicate_content_count": duplicate_existing_reference_count,
            "duplicate_existing_reference_count": duplicate_existing_reference_count,
            "duplicate_declared_corpus_count": 0,
            "total_reference_count": len(reference_gpx),
        }

    corpus_root = Path(corpus_value).expanduser().resolve()
    if not corpus_root.is_dir():
        return reference_gpx, list(source_records), {
            "status": "declared_path_missing",
            "declared_corpus_path": str(corpus_root),
            "additional_reference_count": 0,
            "duplicate_content_count": duplicate_existing_reference_count,
            "duplicate_existing_reference_count": duplicate_existing_reference_count,
            "duplicate_declared_corpus_count": 0,
            "total_reference_count": len(reference_gpx),
        }

    candidates = sorted(
        path.resolve()
        for path in corpus_root.rglob("*")
        if path.is_file() and path.suffix.lower() == ".gpx"
    )
    seen_hashes = {
        sha256_file(path)
        for path in (primary_gpx, *reference_gpx)
    }
    additional_paths: list[Path] = []
    additional_records: list[dict[str, Any]] = []
    duplicate_declared_corpus_count = 0
    for path in candidates:
        digest = sha256_file(path)
        if digest in seen_hashes:
            duplicate_declared_corpus_count += 1
            continue
        seen_hashes.add(digest)
        additional_paths.append(path)
        additional_records.append(
            {
                "role": "reference_track",
                "source_ref": (
                    "material:gpx_corpus/"
                    f"{path.relative_to(corpus_root).as_posix()}"
                ),
                "original_path": str(path),
                "sha256": digest,
                "size_bytes": path.stat().st_size,
            }
        )

    merged_references = (*reference_gpx, *additional_paths)
    return (
        merged_references,
        [*source_records, *additional_records],
        {
            "status": "completed",
            "declared_corpus_path": str(corpus_root),
            "declared_gpx_count": len(candidates),
            "additional_reference_count": len(additional_paths),
            "duplicate_content_count": (
                duplicate_existing_reference_count
                + duplicate_declared_corpus_count
            ),
            "duplicate_existing_reference_count": (
                duplicate_existing_reference_count
            ),
            "duplicate_declared_corpus_count": duplicate_declared_corpus_count,
            "total_reference_count": len(merged_references),
        },
    )


def _deduplicate_existing_reference_gpx(
    *,
    primary_gpx: Path,
    reference_gpx: tuple[Path, ...],
    source_records: list[dict[str, Any]],
) -> tuple[tuple[Path, ...], list[dict[str, Any]], int]:
    seen_hashes = {sha256_file(primary_gpx)}
    unique_references: list[Path] = []
    unique_reference_hashes: set[str] = set()
    duplicate_count = 0
    for path in reference_gpx:
        digest = sha256_file(path)
        if digest in seen_hashes:
            duplicate_count += 1
            continue
        seen_hashes.add(digest)
        unique_reference_hashes.add(digest)
        unique_references.append(path)

    filtered_records: list[dict[str, Any]] = []
    retained_reference_hashes: set[str] = set()
    for record in source_records:
        if record.get("role") != "reference_track":
            filtered_records.append(record)
            continue
        digest = _optional_text(record.get("sha256"))
        if (
            digest not in unique_reference_hashes
            or digest in retained_reference_hashes
        ):
            continue
        retained_reference_hashes.add(digest)
        filtered_records.append(record)

    return tuple(unique_references), filtered_records, duplicate_count


def _source_material_manifest(
    *,
    source_root: Path,
    source_project: dict[str, Any],
    source_manifest: dict[str, Any],
) -> tuple[Path | None, dict[str, Any]]:
    """Compatibility wrapper for source preflight and persisted job bindings."""
    del source_project, source_manifest
    inputs = resolve_workspace_preparation_inputs(source_root)
    return inputs.material_root, inputs.material_manifest


def _clone_receipt(
    *,
    request: WorkspaceCloneRequest,
    status: str,
    source_records: list[dict[str, Any]],
    import_manifest: dict[str, Any],
    preparation_manifest: dict[str, Any] | None,
    material_root: Path | None,
    reference_discovery: dict[str, Any],
    mcp_rebinding: dict[str, Any] | None,
    osm_input_policy: dict[str, Any],
    route_context_source_handoff: dict[str, Any] | None,
    error: str | None = None,
) -> dict[str, Any]:
    normalized_layers = (
        preparation_manifest.get("normalized_layers", [])
        if preparation_manifest is not None
        else []
    )
    return {
        "schema_version": "scout.dashboard.workspace_clone.v1",
        "artifact_kind": "dashboard_workspace_clone_receipt",
        "status": status,
        "source_project_id": request.source_project_id,
        "target_project_id": request.target_project_id,
        "requested_by": request.requested_by,
        "completed_at": _utc_now(),
        "clone_strategy": "clean_import_from_source_inbox_then_map_preparation",
        "source_inputs": source_records,
        "material_root": str(material_root) if material_root is not None else None,
        "reference_discovery": reference_discovery,
        "mcp_evidence_rebinding": mcp_rebinding,
        "osm_input_policy": osm_input_policy,
        "route_context_source_handoff": route_context_source_handoff,
        "stages": {
            "gpx_import": {
                "status": "completed",
                "source_file_count": import_manifest.get("counts", {}).get(
                    "source_file_count", len(source_records)
                ),
            },
            "map_preparation": {
                "status": (
                    preparation_manifest.get("validation", {}).get("status", "completed")
                    if preparation_manifest is not None
                    else "failed"
                ),
                "normalized_layers": normalized_layers,
                "layer_count": len(normalized_layers),
            },
            "qgis_terrain_feature_stack": _qgis_terrain_stage(
                preparation_manifest
            ),
        },
        "dynamic_evidence_policy": {
            "weather_cwa_gee_overpass_refreshable": True,
            "connected_refresh_rewrites_primary_layer_manifest": False,
            "geology_runtime_provider_refreshable": True,
            "geology_frozen_at_preparation": False,
        },
        "error": error,
        "boundary": {
            "source_workspace_mutated": False,
            "target_overwrite_allowed": False,
            "candidate_only": True,
            "runtime_safety_truth": False,
            "phase1_runtime_mutation_allowed": False,
        },
    }


def _qgis_terrain_stage(
    preparation_manifest: dict[str, Any] | None,
) -> dict[str, Any]:
    stage = (
        preparation_manifest.get("qgis_terrain_feature_stack")
        if preparation_manifest is not None
        else None
    )
    if isinstance(stage, dict):
        return stage
    return {
        "status": "not_run",
        "actual_processor": "not_run",
        "fallback_used": False,
        "python_dtm_processing_used": False,
    }


def _clone_completion_status(
    preparation_manifest: dict[str, Any],
    *,
    qgis_terrain_stage: dict[str, Any],
) -> str:
    normalized_layers = set(preparation_manifest.get("normalized_layers") or [])
    if "terrain" not in normalized_layers:
        return "completed"
    if qgis_terrain_stage.get("status") == "completed":
        return "completed"
    return "completed_with_degraded_terrain"


def _write_clone_receipt(project_root: Path, receipt: dict[str, Any]) -> None:
    path = project_root / WORKSPACE_CLONE_RECEIPT_REF
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(receipt, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
    finally:
        temporary_path.unlink(missing_ok=True)


def _select_osm_preparation_input(
    *,
    configured_path: Path | None,
    configured_sha256: str | None,
    osmium_bin: str,
    allow_network_fetch: bool,
    network_mode: str,
) -> tuple[Path | None, dict[str, Any]]:
    if configured_path is None:
        return None, {
            "status": "not_configured",
            "fallback": (
                "overpass_explicit_fetch"
                if allow_network_fetch and network_mode == "explicit-fetch"
                else "none"
            ),
        }
    parser_available = _osm_pbf_parser_available(osmium_bin)
    policy = {
        "configured_path": configured_path.as_posix(),
        "configured_sha256": configured_sha256,
        "osmium_bin": osmium_bin,
        "parser_available": parser_available,
    }
    if parser_available:
        return configured_path, {
            **policy,
            "status": "local_pbf_selected",
            "fallback": "not_needed",
        }
    fallback = (
        "overpass_explicit_fetch"
        if allow_network_fetch and network_mode == "explicit-fetch"
        else "none"
    )
    return None, {
        **policy,
        "status": "local_pbf_skipped_parser_unavailable",
        "fallback": fallback,
        "reason": (
            "Python osmium package is unavailable in the active Dashboard "
            "runtime; the osmium CLI alone is insufficient for the current "
            "Scout conversion path"
        ),
    }


def _osm_pbf_parser_available(osmium_bin: str) -> bool:
    del osmium_bin
    return importlib.util.find_spec("osmium") is not None


def _rebound_mcp_evidence_input(
    *,
    source_path: Path | None,
    source_project_id: str,
    target_project_id: str,
    workspace_root: Path,
) -> tuple[Path | None, dict[str, Any] | None]:
    if source_path is None:
        return None, None
    evidence = load_named_point_evidence(source_path)
    if evidence.project_id != source_project_id:
        raise ValueError(
            "source MCP named-point evidence project_id does not match source workspace"
        )
    rebound = evidence.model_copy(update={"project_id": target_project_id})
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".scout-clone-mcp-{target_project_id}.",
        suffix=".json",
        dir=workspace_root,
    )
    temporary_path = Path(temporary_name)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(rebound.to_json())
        handle.flush()
        os.fsync(handle.fileno())
    return temporary_path, {
        "source_project_id": source_project_id,
        "target_project_id": target_project_id,
        "source_sha256": sha256_file(source_path),
        "rebound_sha256": sha256_file(temporary_path),
        "changed_fields": ["project_id"],
        "source_path_preserved_in_evidence": True,
        "candidate_only": True,
        "runtime_safety_truth": False,
    }


def _route_context_source_handoff_payload(
    *,
    source_root: Path,
    source_project: dict[str, Any],
    source_project_id: str,
    target_project_id: str,
) -> dict[str, Any] | None:
    source_ref = _optional_text(source_project.get("web_case_evidence_ref"))
    if source_ref is None:
        source_ref = "outputs/layers/normalized/web_case_evidence.json"
    source_path = _safe_source_relative_path(source_root, source_ref)
    if source_path is None or not source_path.is_file():
        return None
    source_payload = _load_json_object(source_path)
    boundary = source_payload.get("boundary")
    if not isinstance(boundary, dict) or boundary.get("runtime_safety_truth") is not False:
        return None
    records: list[dict[str, str]] = []
    seen_urls: set[str] = set()
    source_statuses = source_payload.get("source_statuses")
    if not isinstance(source_statuses, list):
        source_statuses = []
    for item in source_statuses:
        record = _bounded_public_route_context_source_record(item)
        if record is None or record["url"] in seen_urls:
            continue
        seen_urls.add(record["url"])
        records.append(record)
        if len(records) >= 32:
            break
    if not records:
        return None
    return {
        "artifact_kind": ROUTE_CONTEXT_SOURCE_HANDOFF_KIND,
        "schema_version": "scout.dashboard.route_context_source_handoff.v1",
        "project_id": target_project_id,
        "source_project_id": source_project_id,
        "target_project_id": target_project_id,
        "source_artifact_ref": source_ref,
        "source_artifact_sha256": sha256_file(source_path),
        "record_count": len(records),
        "records": records,
        "boundary": {
            "candidate_only": True,
            "runtime_safety_truth": False,
            "raw_source_payload_embedded": False,
            "source_workspace_mutation_allowed": False,
            "network_fetch_requires_explicit_preparation": True,
        },
    }


def _write_route_context_source_handoff(
    *,
    target_root: Path,
    payload: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if payload is None:
        return None
    target_path = target_root / ROUTE_CONTEXT_SOURCE_HANDOFF_REF
    target_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = target_path.with_suffix(target_path.suffix + ".tmp")
    temporary_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary_path.replace(target_path)
    project_path = target_root / "project.json"
    project = _load_json_object(project_path)
    project.update(
        {
            "route_context_source_records_ref": (
                ROUTE_CONTEXT_SOURCE_HANDOFF_REF.as_posix()
            ),
            "route_context_source_record_count": payload["record_count"],
            "route_context_source_handoff_sha256": sha256_file(target_path),
        }
    )
    project_path.write_text(
        json.dumps(project, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return {
        "status": "ready_for_explicit_fetch",
        "ref": ROUTE_CONTEXT_SOURCE_HANDOFF_REF.as_posix(),
        "record_count": payload["record_count"],
        "source_artifact_ref": payload["source_artifact_ref"],
        "source_artifact_sha256": payload["source_artifact_sha256"],
        "candidate_only": True,
        "runtime_safety_truth": False,
    }


def _safe_source_relative_path(source_root: Path, ref: str) -> Path | None:
    relative = Path(ref)
    if relative.is_absolute() or ".." in relative.parts:
        return None
    root = source_root.resolve()
    resolved = (root / relative).resolve()
    return resolved if resolved.is_relative_to(root) else None


def _bounded_public_route_context_source_record(
    item: Any,
) -> dict[str, str] | None:
    if not isinstance(item, dict):
        return None
    source_tier = _optional_text(item.get("source_tier"))
    url = _optional_text(item.get("url"))
    if source_tier not in {"P0", "P1"} or url is None:
        return None
    parsed = urlparse(url)
    hostname = parsed.hostname
    if parsed.scheme not in {"http", "https"} or not hostname:
        return None
    if hostname.lower() == "localhost" or hostname.lower().endswith(".localhost"):
        return None
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        address = None
    if address is not None and (
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_reserved
    ):
        return None
    source_id = _optional_text(item.get("source_id")) or hashlib.sha256(
        url.encode("utf-8")
    ).hexdigest()[:16]
    return {
        "source_id": source_id,
        "source_tier": source_tier,
        "source_family": (
            _optional_text(item.get("source_family")) or "route_context_source"
        ),
        "label": _optional_text(item.get("label")) or hostname,
        "url": url,
    }


def _load_json_object(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object: {path}")
    return payload


def _existing_file(value: Any) -> Path | None:
    if not isinstance(value, str) or not value.strip():
        return None
    path = Path(value).expanduser().resolve()
    return path if path.is_file() else None


def _optional_text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


def _positive_int(value: Any, *, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
