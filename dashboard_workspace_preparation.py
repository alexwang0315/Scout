"""Replay a workspace's declared raw inputs through the full preparation pipeline."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pretrip_import import PretripPreparationInputError, validate_dtm_raster_source
from pretrip_layer_preparation import (
    DEFAULT_LAYERS,
    LayerPreparationRequest,
    _validate_request,
    run_layer_preparation,
)
from pretrip_source_ingest import sha256_file


PREPARATION_OPTION_FIELDS = frozenset({
    "layers", "profile", "network_mode", "allow_network_fetch", "prepare_cwa_imagery",
    "bbox", "route_evidence_bundle", "route_corridor_m", "reference_track_corridor_m",
    "ai_mode", "ai_output_policy", "imagery_min_zoom", "imagery_max_zoom",
    "seed_imagery_cache", "imagery_provider_allows_offline_prefetch",
    "imagery_seed_max_tiles", "imagery_cache_root", "imagery_cache_fallback_project_ids",
    "osm_pbf_path", "osm_pbf_source_url", "osm_pbf_cache_ttl_days", "osmium_bin",
    "run_post_layer_enrichments", "run_map_preparation_spec_artifacts",
    "publish_preparation_outputs", "run_qgis_terrain_workflow",
    "qgis_status_retry_attempts", "qgis_status_retry_interval_s",
    "qgis_terrain_analysis_margin_m", "qgis_route_contact_distance_m",
    "qgis_terrain_workflow_timeout_s", "qgis_terrain_poll_interval_s", "prepared_at",
})
_REQUIRED_FULL_PREPARATION_FLAGS = frozenset({
    "run_post_layer_enrichments", "run_map_preparation_spec_artifacts",
    "publish_preparation_outputs", "run_qgis_terrain_workflow",
})


@dataclass(frozen=True)
class WorkspacePreparationInputs:
    material_root: Path | None
    material_manifest: dict[str, Any]
    dtm_dirs: tuple[Path, ...]
    dtm_rasters: tuple[dict[str, Any], ...]
    source: str
    local_osm_pbf: dict[str, Any] | None = None


def build_workspace_preparation_request(
    project_root: Path | str,
    *,
    source_project_id: str | None = None,
    requested_by: str = "dashboard_operator",
    preparation_options: dict[str, Any] | None = None,
) -> LayerPreparationRequest:
    """Read-only preflight; never substitute a machine-specific source or project."""
    root = Path(project_root).expanduser().resolve()
    project = _load_object(root / "project.json")
    project_id = project.get("project_id")
    if project_id != root.name:
        raise ValueError("preparation project_id must match the selected workspace directory")
    options = dict(preparation_options or {})
    unknown = set(options) - PREPARATION_OPTION_FIELDS
    if unknown:
        raise ValueError(f"unsupported preparation options: {', '.join(sorted(unknown))}")
    for key in (
        "allow_network_fetch", "prepare_cwa_imagery", "seed_imagery_cache",
        "imagery_provider_allows_offline_prefetch", "run_post_layer_enrichments",
        "run_map_preparation_spec_artifacts", "publish_preparation_outputs",
        "run_qgis_terrain_workflow",
    ):
        if key in options and not isinstance(options[key], bool):
            raise ValueError(f"{key} must be a boolean")
    disabled = [key for key in sorted(_REQUIRED_FULL_PREPARATION_FLAGS) if options.get(key) is False]
    if disabled:
        raise ValueError(f"full workspace preparation requires: {', '.join(disabled)}")
    sources = resolve_workspace_preparation_inputs(root, preparation_options=options)
    osm = sources.local_osm_pbf or {}
    values: dict[str, Any] = {
        "layers": DEFAULT_LAYERS,
        "profile": "mac-workstation",
        "network_mode": "no-network",
        "allow_network_fetch": False,
        "prepare_cwa_imagery": False,
        "route_corridor_m": 500.0,
        "reference_track_corridor_m": 300.0,
        "imagery_min_zoom": 5,
        "imagery_max_zoom": 14,
        "imagery_cache_fallback_project_ids": (
            (source_project_id,) if source_project_id else ()
        ),
        "osm_pbf_path": osm.get("path"),
        "osm_pbf_source_url": osm.get("source_url"),
        "osm_pbf_cache_ttl_days": osm.get("cache_ttl_days", 30),
        **{key: True for key in _REQUIRED_FULL_PREPARATION_FLAGS},
    }
    values.update(options)  # Presence, including explicit False/None, is intentional.
    if values["network_mode"] not in {"no-network", "explicit-fetch"}:
        raise ValueError("unsupported preparation network_mode")
    if not (values["allow_network_fetch"] and values["network_mode"] == "explicit-fetch"):
        # Preserve Clone's existing no-network behavior; seeding requires both gates.
        values["seed_imagery_cache"] = False
    for key in ("layers", "imagery_cache_fallback_project_ids"):
        value = values[key]
        if not isinstance(value, (tuple, list)) or not all(isinstance(item, str) for item in value):
            raise ValueError(f"{key} must be a list of strings")
        values[key] = tuple(value)
    cache_root = (root / "cache" / "raster-tiles").resolve()
    configured_cache = values.get("imagery_cache_root")
    if configured_cache is not None and Path(configured_cache).expanduser().resolve() != cache_root:
        raise ValueError("imagery_cache_root must remain in the selected workspace")
    values["imagery_cache_root"] = cache_root
    for key in ("osm_pbf_path", "route_evidence_bundle"):
        value = values.get(key)
        if value is not None:
            path = Path(value).expanduser()
            if not path.is_absolute():
                path = root / path
            values[key] = _require_source(path, field=key, directory=False)
    route_bundle = values.get("route_evidence_bundle")
    if route_bundle is not None and root not in route_bundle.parents:
        raise ValueError("route_evidence_bundle must belong to the selected workspace")
    values.update({
        "project_id": project_id,
        "project_root": root,
        "qgis_requested_by": requested_by,
    })
    request = LayerPreparationRequest(**values)
    _validate_request(request)
    return request


def prepare_imported_workspace(
    project_root: Path | str,
    *,
    source_project_id: str | None = None,
    requested_by: str = "dashboard_operator",
    preparation_options: dict[str, Any] | None = None,
) -> dict[str, Any]:
    request = build_workspace_preparation_request(
        project_root,
        source_project_id=source_project_id,
        requested_by=requested_by,
        preparation_options=preparation_options,
    )
    return run_layer_preparation(request)


def resolve_workspace_preparation_inputs(
    project_root: Path | str, *, preparation_options: dict[str, Any] | None = None,
) -> WorkspacePreparationInputs:
    """Resolve saved input declarations, with a bounded legacy metadata fallback.

    Legacy coverage contributes original source paths only. Its terrain output,
    tiles, and readiness values are never reused as preparation results.
    """
    root = Path(project_root).expanduser().resolve()
    project = _load_object(root / "project.json")
    source_manifest = _load_optional_object(root / "inbox" / "source_manifest.json")
    import_manifest = _load_optional_object(root / "outputs" / "import_manifest.json")
    for payload in (project, source_manifest, import_manifest):
        if payload.get("project_id") not in {None, root.name}:
            raise ValueError("preparation source manifest project_id does not match workspace")
    saved = source_manifest.get("preparation_inputs") or import_manifest.get("inputs", {}).get("preparation_inputs")
    if saved is not None and not isinstance(saved, dict):
        raise ValueError("preparation_inputs must be an object")
    material_root: Path | None = None
    material_manifest: dict[str, Any] = {}
    source = "saved_preparation_inputs" if saved else "legacy_raw_source_metadata"
    if saved and saved.get("material_root"):
        material_root = _require_source(saved["material_root"], field="material_root", directory=True)
        manifest_path = saved.get("material_manifest_path")
        if manifest_path:
            path = _require_source(manifest_path, field="material_manifest_path", directory=False)
            if path != material_root / "material_manifest.json":
                raise ValueError("material manifest must belong to the declared material root")
            expected = saved.get("material_manifest_sha256")
            if expected and sha256_file(path) != expected:
                raise PretripPreparationInputError(
                    field="material_manifest_sha256", path=path, code="PREPARATION_SOURCE_CHANGED"
                )
            material_manifest = _load_object(path)
    elif not saved:
        material_root, material_manifest = _legacy_material_manifest(root, project, source_manifest)
    material_sources = material_manifest.get("sources", {}) or {}
    if not isinstance(material_sources, dict):
        raise ValueError("material manifest sources must be an object")
    dirs = list((saved or {}).get("dtm_dirs", material_sources.get("dtm_dirs", [])))
    rasters = list((saved or {}).get("dtm_rasters", material_sources.get("dtm_rasters", [])))
    if not saved:
        coverage_ref = project.get("dtm_coverage_summary_ref") or "normalized/terrain/dtm_coverage_summary.json"
        coverage_path = (root / coverage_ref).resolve()
        if root not in coverage_path.parents:
            raise ValueError("DTM coverage metadata ref must remain inside workspace")
        coverage = _load_optional_object(coverage_path)
        dirs.extend(coverage.get("source_dirs", []))
        rasters.extend(coverage.get("raster_sources", []))
    resolved_dirs = tuple(dict.fromkeys(
        _require_source(value, field="dtm_dirs", directory=True) for value in dirs
    ))
    resolved_rasters: dict[str, dict[str, Any]] = {}
    for raster in rasters:
        if not isinstance(raster, dict) or not raster.get("path"):
            raise ValueError("DTM raster source must declare a path")
        path = _require_source(raster["path"], field="dtm_rasters", directory=False)
        _reject_derived_workspace_source(path, field="dtm_source")
        validated = validate_dtm_raster_source({**raster, "path": str(path)})
        previous = resolved_rasters.get(str(path))
        if (previous and previous.get("crs_evidence_sha256") and validated.crs_evidence_sha256
                and previous["crs_evidence_sha256"] != validated.crs_evidence_sha256):
            raise PretripPreparationInputError(
                field="crs_evidence_sha256", path=validated.crs_evidence or path,
                code="PREPARATION_SOURCE_CONFLICT",
            )
        if previous and previous.get("crs_evidence_sha256") and not validated.crs_evidence_sha256:
            continue
        resolved_rasters[str(path)] = validated.model_dump(mode="json")
    for path in resolved_dirs:
        _reject_derived_workspace_source(path, field="dtm_source")
    for key, directory in (("mcp_named_point_evidence", False), ("gpx_corpus", True)):
        declaration = material_sources.get(key)
        value = declaration.get("path") if isinstance(declaration, dict) else declaration
        if value:
            _require_source(value, field=key, directory=directory)
    return WorkspacePreparationInputs(
        material_root=material_root,
        material_manifest=material_manifest,
        dtm_dirs=resolved_dirs,
        dtm_rasters=tuple(resolved_rasters.values()),
        source=source,
        local_osm_pbf=_resolve_original_osm_pbf(
            root=root, project=project, material_root=material_root,
            material_sources=material_sources, options=preparation_options or {},
        ),
    )


def _resolve_original_osm_pbf(
    *, root: Path, project: dict[str, Any], material_root: Path | None,
    material_sources: dict[str, Any], options: dict[str, Any],
) -> dict[str, Any] | None:
    declaration: dict[str, Any] = {}
    declaration_source = "material_manifest"
    metadata_ref: str | None = None
    base = root
    if "local_osm_pbf" in material_sources:
        value = material_sources["local_osm_pbf"]
        if value is not None:
            if not isinstance(value, dict):
                raise ValueError("material local_osm_pbf must be an object")
            declaration = dict(value)
            base = material_root or root
            metadata_ref = str(base / "material_manifest.json")
    elif project.get("osm_pbf_source_ref"):
        declaration = {
            "path": project["osm_pbf_source_ref"],
            "sha256": project.get("osm_pbf_source_sha256"),
            "source_url": project.get("osm_pbf_source_url"),
            "cache_ttl_days": project.get("osm_pbf_cache_ttl_days", 30),
        }
        declaration_source = "project_original_pbf_metadata"
        metadata_ref = str(root / "project.json")

    def source_path(value: Any, relative_to: Path) -> Path:
        if not isinstance(value, (str, Path)) or not str(value).strip():
            raise ValueError("local_osm_pbf must declare a nonempty original path")
        path = Path(value).expanduser()
        return (path if path.is_absolute() else relative_to / path).resolve()

    explicit_path = "osm_pbf_path" in options
    if explicit_path:
        if options["osm_pbf_path"] is None:
            return None
        selected_path = source_path(options["osm_pbf_path"], root)
        original_path = declaration.get("path")
        if original_path is None or source_path(original_path, base) != selected_path:
            declaration = {"path": str(selected_path)}
            metadata_ref = None
        declaration_source = "preparation_options"
    else:
        if not declaration:
            return None
        selected_path = source_path(declaration.get("path"), base)
    selected_path = _require_source(selected_path, field="local_osm_pbf", directory=False)
    _reject_derived_workspace_source(selected_path, field="local_osm_pbf")
    if selected_path.suffix.lower() != ".pbf":
        raise ValueError("local_osm_pbf original source must be a PBF file")
    expected_hash = declaration.get("sha256")
    if declaration_source == "project_original_pbf_metadata" and not expected_hash:
        raise PretripPreparationInputError(
            field="osm_pbf_source_sha256", path=selected_path,
            code="PREPARATION_SOURCE_HASH_MISSING",
        )
    digest = sha256_file(selected_path)
    if expected_hash is not None and expected_hash != digest:
        raise PretripPreparationInputError(
            field="local_osm_pbf.sha256", path=selected_path, code="PREPARATION_SOURCE_CHANGED"
        )
    source_url = options.get("osm_pbf_source_url", declaration.get("source_url"))
    if source_url is not None and not isinstance(source_url, str):
        raise ValueError("local_osm_pbf source_url must be a string or None")
    ttl_days = options.get("osm_pbf_cache_ttl_days", declaration.get("cache_ttl_days", 30))
    if not isinstance(ttl_days, int) or isinstance(ttl_days, bool) or ttl_days <= 0:
        raise ValueError("local_osm_pbf cache_ttl_days must be a positive integer")
    return {
        "path": str(selected_path), "sha256": digest,
        "source_url": source_url, "cache_ttl_days": ttl_days,
        "declaration_source": declaration_source, "metadata_ref": metadata_ref,
    }


def _legacy_material_manifest(
    root: Path, project: dict[str, Any], source_manifest: dict[str, Any]
) -> tuple[Path | None, dict[str, Any]]:
    declared_root = project.get("material_root")
    if declared_root:
        path = _require_source(declared_root, field="material_root", directory=True)
        return path, _load_optional_object(path / "material_manifest.json")
    candidates: list[Path] = []
    values = [project.get("mcp_named_point_evidence_source_path")]
    values.extend(item.get("original_path") for item in source_manifest.get("sources", []) if isinstance(item, dict))
    for value in values:
        if isinstance(value, str) and value:
            path = Path(value).expanduser().resolve()
            # A missing old original GPX is legal only because clone separately
            # verifies the byte-identical raw file retained in its source inbox.
            candidates.extend(path.parents)
    candidates.extend(root.parents)
    for candidate in dict.fromkeys(candidates):
        manifest_path = candidate / "material_manifest.json"
        if manifest_path.is_file():
            return candidate, _load_object(manifest_path)
    return None, {}


def _reject_derived_workspace_source(path: Path, *, field: str) -> None:
    for parent in (path, *path.parents):
        if parent.name in {"outputs", "normalized", "cache"} and (parent.parent / "project.json").is_file():
            raise PretripPreparationInputError(field=field, path=path, code="PREPARATION_SOURCE_IS_DERIVED")


def _require_source(value: Path | str, *, field: str, directory: bool) -> Path:
    if not isinstance(value, (str, Path)) or not str(value).strip():
        raise ValueError(f"{field} must declare a nonempty path")
    path = Path(value).expanduser().resolve()
    if not (path.is_dir() if directory else path.is_file()):
        raise PretripPreparationInputError(field=field, path=path)
    return path


def _load_object(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object: {path}")
    return payload


def _load_optional_object(path: Path) -> dict[str, Any]:
    return _load_object(path) if path.is_file() else {}
