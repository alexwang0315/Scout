from __future__ import annotations

import importlib.util
import json
import os
import re
import shutil
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Literal

from pretrip_import import PretripImportRequest, run_pretrip_import
from pretrip_layer_preparation import (
    DEFAULT_LAYERS,
    LayerPreparationRequest,
    run_layer_preparation,
)
from pretrip_mcp_synthesis import load_named_point_evidence
from pretrip_source_ingest import sha256_file


PROJECT_ID_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+$")
WORKSPACE_CLONE_RECEIPT_REF = Path("outputs/workspace_clone_receipt.json")

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
    material_root, material_manifest = _source_material_manifest(
        source_root=source_root,
        source_project=source_project,
        source_manifest=source_manifest,
    )
    material_sources = material_manifest.get("sources", {})
    if not isinstance(material_sources, dict):
        material_sources = {}
    reference_gpx, source_records, reference_discovery = (
        _discover_declared_material_reference_gpx(
            material_sources=material_sources,
            primary_gpx=primary_gpx,
            reference_gpx=reference_gpx,
            source_records=source_records,
        )
    )
    dtm_dirs = tuple(
        path
        for value in material_sources.get("dtm_dirs", [])
        if isinstance(value, str)
        for path in (Path(value).expanduser().resolve(),)
        if path.is_dir()
    )
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
                dtm_dirs=dtm_dirs,
                mcp_named_point_evidence=mcp_named_point_evidence,
                overwrite=False,
                import_timestamp=imported_at,
                import_stage="pretrip",
            )
        )
    finally:
        if mcp_named_point_evidence is not None:
            mcp_named_point_evidence.unlink(missing_ok=True)

    local_osm_pbf = material_sources.get("local_osm_pbf", {})
    if not isinstance(local_osm_pbf, dict):
        local_osm_pbf = {}
    configured_osm_pbf_path = _existing_file(local_osm_pbf.get("path"))
    osm_pbf_path, osm_input_policy = _select_osm_preparation_input(
        configured_path=configured_osm_pbf_path,
        configured_sha256=_optional_text(local_osm_pbf.get("sha256")),
        osmium_bin=request.osmium_bin,
        allow_network_fetch=request.allow_network_fetch,
        network_mode=request.network_mode,
    )
    osm_pbf_source_url = _optional_text(local_osm_pbf.get("source_url"))
    osm_pbf_cache_ttl_days = _positive_int(
        local_osm_pbf.get("cache_ttl_days"),
        default=30,
    )

    try:
        preparation_manifest = preparation_runner(
            LayerPreparationRequest(
                project_id=request.target_project_id,
                project_root=target_root,
                layers=request.layers,
                profile=request.profile,
                network_mode=request.network_mode,
                allow_network_fetch=request.allow_network_fetch,
                prepare_cwa_imagery=request.prepare_cwa_imagery,
                route_corridor_m=request.route_corridor_m,
                reference_track_corridor_m=request.reference_track_corridor_m,
                imagery_min_zoom=request.imagery_min_zoom,
                imagery_max_zoom=request.imagery_max_zoom,
                seed_imagery_cache=(
                    request.seed_imagery_cache
                    and request.network_mode == "explicit-fetch"
                    and request.allow_network_fetch
                ),
                imagery_provider_allows_offline_prefetch=(
                    request.imagery_provider_allows_offline_prefetch
                ),
                imagery_seed_max_tiles=request.imagery_seed_max_tiles,
                imagery_cache_root=(
                    target_root / "cache" / "raster-tiles"
                ).resolve(),
                imagery_cache_fallback_project_ids=(request.source_project_id,),
                run_post_layer_enrichments=True,
                run_map_preparation_spec_artifacts=True,
                osm_pbf_path=osm_pbf_path,
                osm_pbf_source_url=osm_pbf_source_url,
                osm_pbf_cache_ttl_days=osm_pbf_cache_ttl_days,
                osmium_bin=request.osmium_bin,
            )
        )
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
                    error=safe_error,
                ),
            )
        raise WorkspaceClonePreparationError(safe_error) from exc

    receipt = _clone_receipt(
        request=request,
        status="completed",
        source_records=source_records,
        import_manifest=import_manifest,
        preparation_manifest=preparation_manifest,
        material_root=material_root,
        reference_discovery=reference_discovery,
        mcp_rebinding=mcp_rebinding,
        osm_input_policy=osm_input_policy,
    )
    _write_clone_receipt(target_root, receipt)
    return {
        "source_project_id": request.source_project_id,
        "target_project_id": request.target_project_id,
        "project_root": str(target_root),
        "status": "completed",
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
    candidates: list[Path] = []
    mcp_source = _existing_file(source_project.get("mcp_named_point_evidence_source_path"))
    if mcp_source is not None:
        candidates.extend(mcp_source.parents)
    for source in source_manifest.get("sources", []):
        if not isinstance(source, dict):
            continue
        original = _existing_file(source.get("original_path"))
        if original is not None:
            candidates.extend(original.parents)
    candidates.extend(source_root.parents)

    seen: set[Path] = set()
    for candidate in candidates:
        resolved = candidate.expanduser().resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        manifest_path = resolved / "material_manifest.json"
        if not manifest_path.is_file():
            continue
        manifest = _load_json_object(manifest_path)
        return resolved, manifest
    return None, {}


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
        "reason": "neither osmium CLI nor Python osmium package is available",
    }


def _osm_pbf_parser_available(osmium_bin: str) -> bool:
    return (
        shutil.which(osmium_bin) is not None
        or importlib.util.find_spec("osmium") is not None
    )


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
