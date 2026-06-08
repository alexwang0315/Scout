from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path
from typing import Any

from admin_local_raster_source import (
    build_local_raster_source_manifest,
    write_local_raster_source_manifest,
)
from admin_local_raster_tiles import (
    build_raster_tile_pyramid_plan,
    cut_raster_tile_pyramid,
    write_raster_tile_plan_manifest,
)


DEFAULT_SCOUT_DATA_ROOT = Path("/data/scout")
DEFAULT_LAYER_ID = "imagery"


def build_offline_map_handoff(
    *,
    project_id: str,
    source_geotiff: Path | str,
    package_root: Path | str,
    source_kmz: Path | str | None = None,
    scout_data_root: Path | str = DEFAULT_SCOUT_DATA_ROOT,
    min_zoom: int = 5,
    max_zoom: int = 14,
    max_tiles: int | None = None,
) -> dict[str, Any]:
    package = Path(package_root).expanduser()
    source_path = Path(source_geotiff).expanduser()
    if not source_path.exists():
        raise FileNotFoundError(source_path)
    kmz_path = Path(source_kmz).expanduser() if source_kmz else None
    if kmz_path is not None and not kmz_path.exists():
        raise FileNotFoundError(kmz_path)

    scout_root = Path(scout_data_root)
    source_dir = package / "raster-sources" / project_id
    tile_cache_root = package / "raster-tiles"
    manifest_dir = (
        package
        / "admin"
        / "pretrip-workspaces"
        / project_id
        / "outputs"
        / "layers"
        / "manifests"
    )
    source_dir.mkdir(parents=True, exist_ok=True)
    manifest_dir.mkdir(parents=True, exist_ok=True)

    packaged_geotiff = source_dir / source_path.name
    if source_path.resolve() != packaged_geotiff.resolve():
        shutil.copy2(source_path, packaged_geotiff)
    packaged_kmz = None
    if kmz_path is not None:
        packaged_kmz = source_dir / kmz_path.name
        if kmz_path.resolve() != packaged_kmz.resolve():
            shutil.copy2(kmz_path, packaged_kmz)

    scout_source_path = scout_root / "raster-sources" / project_id / source_path.name
    local_manifest = build_local_raster_source_manifest(
        packaged_geotiff,
        project_id=project_id,
        layer_id=DEFAULT_LAYER_ID,
        recommended_cache_root=scout_root / "raster-sources",
    )
    scout_manifest = build_local_raster_source_manifest(
        packaged_geotiff,
        project_id=project_id,
        layer_id=DEFAULT_LAYER_ID,
        recommended_cache_root=scout_root / "raster-sources",
        runtime_source_path=scout_source_path,
    )
    scout_manifest["handoff"] = {
        "artifact_kind": "pretrip_offline_map_handoff_source",
        "transport": "mac_build_to_scout_rsync",
        "source_role": "user_provided_imagery",
        "scout_data_root": str(scout_root),
        "scout_source_path": str(scout_source_path),
        "scout_kmz_path": (
            str(scout_root / "raster-sources" / project_id / packaged_kmz.name)
            if packaged_kmz
            else None
        ),
    }

    plan = build_raster_tile_pyramid_plan(
        local_manifest,
        cache_root=tile_cache_root,
        min_zoom=min_zoom,
        max_zoom=max_zoom,
    )
    cut_summary = cut_raster_tile_pyramid(
        local_manifest,
        plan,
        dry_run=False,
        max_tiles=max_tiles,
    )
    scout_plan = dict(plan)
    scout_plan["cache_root"] = str(scout_root / "raster-tiles")
    scout_plan["source_geotiff_path"] = str(scout_source_path)
    scout_plan["handoff"] = {
        "artifact_kind": "pretrip_offline_map_handoff_tiles",
        "transport": "mac_build_to_scout_rsync",
        "source_role": "user_provided_imagery",
        "package_tile_cache_root": str(tile_cache_root),
        "scout_tile_cache_root": str(scout_root / "raster-tiles"),
    }

    source_manifest_ref = (
        "outputs/layers/manifests/"
        f"{project_id}.local_raster_source_manifest.json"
    )
    tile_plan_ref = (
        "outputs/layers/manifests/"
        f"{project_id}.raster_tile_pyramid_plan.json"
    )
    source_manifest_path = manifest_dir / f"{project_id}.local_raster_source_manifest.json"
    tile_plan_path = manifest_dir / f"{project_id}.raster_tile_pyramid_plan.json"
    write_local_raster_source_manifest(scout_manifest, source_manifest_path)
    write_raster_tile_plan_manifest(scout_plan, tile_plan_path)

    handoff = {
        "artifact_kind": "pretrip_offline_map_handoff_package",
        "status": cut_summary["status"],
        "project_id": project_id,
        "source_role": "user_provided_imagery",
        "source_files": {
            "geotiff": str(packaged_geotiff),
            "kmz": str(packaged_kmz) if packaged_kmz else None,
        },
        "scout_targets": {
            "data_root": str(scout_root),
            "raster_sources": str(scout_root / "raster-sources" / project_id),
            "raster_tiles": str(scout_root / "raster-tiles"),
            "workspace": str(scout_root / "admin" / "pretrip-workspaces" / project_id),
        },
        "workspace_project_refs": {
            "imagery_manifest_ref": source_manifest_ref,
            "local_raster_manifest_ref": source_manifest_ref,
            "raster_tile_manifest_ref": tile_plan_ref,
            "imagery_source_kind": "user_provided_local_geotiff",
            "imagery_source_tiff_ref": str(scout_source_path),
            "imagery_source_kmz_ref": (
                str(scout_root / "raster-sources" / project_id / packaged_kmz.name)
                if packaged_kmz
                else None
            ),
            "imagery_tile_cache_root": str(scout_root / "raster-tiles"),
        },
        "manifests": {
            "source_manifest": str(source_manifest_path),
            "tile_plan": str(tile_plan_path),
        },
        "tile_cut_summary": cut_summary,
        "boundary": {
            "mac_build_required": True,
            "scout_runtime_tile_cutting_required": False,
            "external_network_required": False,
            "repo_fixture_write_allowed": False,
            "raw_raster_committed_to_repo_allowed": False,
            "runtime_safety_truth": False,
        },
        "rsync_hint": (
            f"rsync -a {package}/ scout.local:{scout_root}/"
        ),
    }
    handoff_path = package / "offline_map_handoff_manifest.json"
    handoff_path.write_text(
        json.dumps(handoff, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return handoff


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Build a Mac-to-Scout pretrip offline map handoff package."
    )
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--source-geotiff", type=Path, required=True)
    parser.add_argument("--source-kmz", type=Path)
    parser.add_argument("--package-root", type=Path, required=True)
    parser.add_argument("--scout-data-root", type=Path, default=DEFAULT_SCOUT_DATA_ROOT)
    parser.add_argument("--min-zoom", type=int, default=5)
    parser.add_argument("--max-zoom", type=int, default=14)
    parser.add_argument("--max-tiles", type=int)
    args = parser.parse_args(argv)

    handoff = build_offline_map_handoff(
        project_id=args.project_id,
        source_geotiff=args.source_geotiff,
        source_kmz=args.source_kmz,
        package_root=args.package_root,
        scout_data_root=args.scout_data_root,
        min_zoom=args.min_zoom,
        max_zoom=args.max_zoom,
        max_tiles=args.max_tiles,
    )
    print(json.dumps(handoff, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
