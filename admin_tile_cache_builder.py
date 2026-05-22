from __future__ import annotations

import argparse
import hashlib
import json
import time
import urllib.request
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from admin_basemap_tiles import (
    DEFAULT_OSM_TILE_URL_TEMPLATE,
    MAX_OSM_ZOOM,
    MIN_OSM_ZOOM,
    normalize_bbox_wgs84,
    slippy_tile_range,
)
from admin_tile_proxy import DEFAULT_OSM_TILE_CACHE_ROOT, osm_tile_cache_path


DEFAULT_TILE_CACHE_CAPACITY_BYTES = 10 * 1024 * 1024 * 1024
DEFAULT_TILE_CACHE_EXPANSION_RATIO = 0.5
DEFAULT_TILE_CACHE_MIN_ZOOM = 5
DEFAULT_TILE_CACHE_MAX_ZOOM = 20
DEFAULT_ESTIMATED_TILE_BYTES = 16 * 1024
DEFAULT_TILE_CACHE_USER_AGENT = (
    "ScoutFusionTileCache/0.1 (+local Scout hardware deployment)"
)
PUBLIC_OSM_TILE_HOST = "tile.openstreetmap.org"

TileFetch = Callable[[str, Mapping[str, str]], bytes | tuple[bytes, str]]


def load_pretrip_project_route_bbox(project_root: Path | str) -> dict[str, float]:
    root = Path(project_root)
    project = _load_json(root / "project.json")
    route_ref = project.get("route_summary_ref")
    if not route_ref:
        raise ValueError("project.json is missing route_summary_ref")
    route_summary = _load_json(root / str(route_ref))
    bbox = (
        route_summary.get("bounds")
        or route_summary.get("bbox")
        or route_summary.get("bbox_wgs84")
    )
    if not isinstance(bbox, Mapping):
        raise ValueError("route summary is missing bounds")
    return normalize_bbox_wgs84(bbox)


def expand_bbox_wgs84(
    bbox: Mapping[str, Any] | object,
    *,
    expansion_ratio: float = DEFAULT_TILE_CACHE_EXPANSION_RATIO,
) -> dict[str, float]:
    if expansion_ratio < 0:
        raise ValueError("expansion_ratio must be non-negative")
    normalized = normalize_bbox_wgs84(bbox)
    lat_span = normalized["north"] - normalized["south"]
    lon_span = normalized["east"] - normalized["west"]
    lat_pad = lat_span * expansion_ratio / 2
    lon_pad = lon_span * expansion_ratio / 2
    return normalize_bbox_wgs84(
        {
            "south": normalized["south"] - lat_pad,
            "west": max(-180.0, normalized["west"] - lon_pad),
            "north": normalized["north"] + lat_pad,
            "east": min(180.0, normalized["east"] + lon_pad),
        }
    )


def build_tile_cache_plan(
    bbox: Mapping[str, Any] | object,
    *,
    cache_root: Path | str = DEFAULT_OSM_TILE_CACHE_ROOT,
    expansion_ratio: float = DEFAULT_TILE_CACHE_EXPANSION_RATIO,
    min_zoom: int = DEFAULT_TILE_CACHE_MIN_ZOOM,
    max_zoom: int = DEFAULT_TILE_CACHE_MAX_ZOOM,
    capacity_limit_bytes: int = DEFAULT_TILE_CACHE_CAPACITY_BYTES,
    estimated_tile_bytes: int = DEFAULT_ESTIMATED_TILE_BYTES,
    tile_url_template: str = DEFAULT_OSM_TILE_URL_TEMPLATE,
    plan_id: str = "admin_tile_cache.chilai_nanhua_day1.v0",
) -> dict[str, Any]:
    if min_zoom < MIN_OSM_ZOOM or max_zoom > MAX_OSM_ZOOM or min_zoom > max_zoom:
        raise ValueError(f"zoom range must be between {MIN_OSM_ZOOM} and {MAX_OSM_ZOOM}")
    if capacity_limit_bytes <= 0:
        raise ValueError("capacity_limit_bytes must be positive")
    if estimated_tile_bytes <= 0:
        raise ValueError("estimated_tile_bytes must be positive")

    normalized = normalize_bbox_wgs84(bbox)
    expanded = expand_bbox_wgs84(normalized, expansion_ratio=expansion_ratio)
    zoom_ranges = [
        _zoom_range(expanded, zoom=z, estimated_tile_bytes=estimated_tile_bytes)
        for z in range(min_zoom, max_zoom + 1)
    ]
    total_tile_count = sum(int(item["tile_count"]) for item in zoom_ranges)
    estimated_total_bytes = total_tile_count * estimated_tile_bytes
    within_capacity = estimated_total_bytes <= capacity_limit_bytes
    public_osm = is_public_osm_tile_template(tile_url_template)
    return {
        "artifact_kind": "admin_tile_cache_plan",
        "plan_id": plan_id,
        "status": "planned_capacity_ok" if within_capacity else "blocked_capacity_limit",
        "cache_root": str(Path(cache_root).expanduser()),
        "hardware_deploy_target": "scout_hardware",
        "requested_bbox_wgs84": normalized,
        "expanded_bbox_wgs84": expanded,
        "bbox_expansion_ratio": expansion_ratio,
        "bbox_expansion_semantics": "increase_width_and_height_by_ratio",
        "min_zoom": min_zoom,
        "max_zoom": max_zoom,
        "zoom_range": f"{min_zoom}-{max_zoom}",
        "tile_url_template": tile_url_template,
        "tile_url_template_is_public_osm": public_osm,
        "source_policy_status": (
            "public_osm_bulk_download_prohibited"
            if public_osm
            else "operator_provider_must_allow_offline_prefetch"
        ),
        "bulk_download_allowed": False if public_osm else None,
        "capacity_limit_bytes": capacity_limit_bytes,
        "capacity_limit_gib": round(capacity_limit_bytes / 1024 / 1024 / 1024, 3),
        "estimated_tile_bytes": estimated_tile_bytes,
        "estimated_total_bytes": estimated_total_bytes,
        "estimated_total_gib": round(estimated_total_bytes / 1024 / 1024 / 1024, 3),
        "within_capacity_limit": within_capacity,
        "total_tile_count": total_tile_count,
        "zoom_ranges": zoom_ranges,
        "downloads_tiles_into_repo": False,
        "repo_fixture_write_allowed": False,
        "notes": [
            "Cache root is outside the repository and is intended for Scout hardware deployment.",
            "The 50 percent bbox expansion increases width and height by 50 percent total, adding 25 percent padding per side.",
            "Public tile.openstreetmap.org bulk/offline prefetch is blocked by policy; use a self-hosted or offline-prefetch-permitted provider to seed real tiles.",
        ],
    }


def build_tile_cache_hardware_manifest(plan: Mapping[str, Any]) -> dict[str, Any]:
    status = (
        "ready_for_permitted_tile_source"
        if plan.get("within_capacity_limit")
        else "blocked_capacity_limit"
    )
    return {
        "artifact_kind": "admin_tile_cache_hardware_manifest",
        "status": status,
        "plan_id": plan["plan_id"],
        "cache_root": plan["cache_root"],
        "hardware_deploy_target": "scout_hardware",
        "capacity_limit_bytes": plan["capacity_limit_bytes"],
        "estimated_total_bytes": plan["estimated_total_bytes"],
        "total_tile_count": plan["total_tile_count"],
        "zoom_range": plan["zoom_range"],
        "source_policy_status": plan["source_policy_status"],
        "bulk_download_allowed": plan["bulk_download_allowed"],
        "runtime_tile_url_template": "/admin/tiles/osm/{z}/{x}/{y}.png",
        "rsync_hint": (
            f"rsync -a --delete {plan['cache_root'].rstrip('/')}/ "
            "scout-hardware:/home/scout/.cache/scout-fusion/osm-tiles/"
        ),
        "repo_fixture_write_allowed": False,
    }


def seed_tile_cache(
    plan: Mapping[str, Any],
    *,
    provider_allows_offline_prefetch: bool = False,
    fetch_tile: TileFetch | None = None,
    dry_run: bool = True,
    max_tiles: int | None = None,
    user_agent: str = DEFAULT_TILE_CACHE_USER_AGENT,
) -> dict[str, Any]:
    if plan.get("within_capacity_limit") is not True:
        raise ValueError("tile cache plan exceeds capacity limit")
    if plan.get("tile_url_template_is_public_osm") is True:
        raise ValueError("public tile.openstreetmap.org bulk/offline prefetch is prohibited")
    if not provider_allows_offline_prefetch:
        raise ValueError("provider_allows_offline_prefetch must be true before seeding")

    tiles_seen = 0
    tiles_written = 0
    tiles_skipped_existing = 0
    bytes_written = 0
    cache_root = Path(str(plan["cache_root"])).expanduser()
    capacity_limit = int(plan["capacity_limit_bytes"])
    source_template = str(plan["tile_url_template"])
    started_at = time.time()
    headers = {"User-Agent": user_agent}

    for tile in iter_plan_tiles(plan):
        if max_tiles is not None and tiles_seen >= max_tiles:
            break
        tiles_seen += 1
        path = osm_tile_cache_path(
            tile["z"],
            tile["x"],
            tile["y"],
            cache_root=cache_root,
        )
        if path.exists():
            tiles_skipped_existing += 1
            continue
        url = source_template.format(z=tile["z"], x=tile["x"], y=tile["y"])
        if dry_run:
            continue
        body = _fetch_tile(url, headers=headers, fetch_tile=fetch_tile)
        if bytes_written + len(body) > capacity_limit:
            return _seed_summary(
                "stopped_capacity_limit",
                plan=plan,
                dry_run=dry_run,
                tiles_seen=tiles_seen,
                tiles_written=tiles_written,
                tiles_skipped_existing=tiles_skipped_existing,
                bytes_written=bytes_written,
                started_at=started_at,
            )
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body)
        tiles_written += 1
        bytes_written += len(body)

    return _seed_summary(
        "dry_run_ready" if dry_run else "seed_complete",
        plan=plan,
        dry_run=dry_run,
        tiles_seen=tiles_seen,
        tiles_written=tiles_written,
        tiles_skipped_existing=tiles_skipped_existing,
        bytes_written=bytes_written,
        started_at=started_at,
    )


def iter_plan_tiles(plan: Mapping[str, Any]) -> list[dict[str, int]]:
    tiles: list[dict[str, int]] = []
    for zoom_range in plan.get("zoom_ranges", []):
        z = int(zoom_range["z"])
        for y in range(int(zoom_range["y_min"]), int(zoom_range["y_max"]) + 1):
            for x in range(int(zoom_range["x_min"]), int(zoom_range["x_max"]) + 1):
                tiles.append({"z": z, "x": x, "y": y})
    return tiles


def write_tile_cache_manifest(manifest: Mapping[str, Any], path: Path | str) -> Path:
    manifest_path = Path(path).expanduser()
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        json.dumps(dict(manifest), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return manifest_path


def is_public_osm_tile_template(tile_url_template: str) -> bool:
    return PUBLIC_OSM_TILE_HOST in tile_url_template.lower()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build Scout admin OSM tile cache plans.")
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--cache-root", type=Path, default=DEFAULT_OSM_TILE_CACHE_ROOT)
    parser.add_argument("--min-zoom", type=int, default=DEFAULT_TILE_CACHE_MIN_ZOOM)
    parser.add_argument("--max-zoom", type=int, default=DEFAULT_TILE_CACHE_MAX_ZOOM)
    parser.add_argument("--bbox-expansion-ratio", type=float, default=0.5)
    parser.add_argument("--capacity-gib", type=float, default=10.0)
    parser.add_argument("--tile-url-template", default=DEFAULT_OSM_TILE_URL_TEMPLATE)
    parser.add_argument("--write-manifest", type=Path)
    args = parser.parse_args(argv)

    bbox = load_pretrip_project_route_bbox(args.project_root)
    plan = build_tile_cache_plan(
        bbox,
        cache_root=args.cache_root,
        expansion_ratio=args.bbox_expansion_ratio,
        min_zoom=args.min_zoom,
        max_zoom=args.max_zoom,
        capacity_limit_bytes=int(args.capacity_gib * 1024 * 1024 * 1024),
        tile_url_template=args.tile_url_template,
    )
    manifest = {
        "plan": plan,
        "hardware_manifest": build_tile_cache_hardware_manifest(plan),
    }
    if args.write_manifest:
        write_tile_cache_manifest(manifest, args.write_manifest)
    print(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def _zoom_range(
    bbox: Mapping[str, Any],
    *,
    zoom: int,
    estimated_tile_bytes: int,
) -> dict[str, Any]:
    x_min, x_max, y_min, y_max = slippy_tile_range(bbox, zoom=zoom)
    tile_count = (x_max - x_min + 1) * (y_max - y_min + 1)
    return {
        "z": zoom,
        "x_min": x_min,
        "x_max": x_max,
        "y_min": y_min,
        "y_max": y_max,
        "tile_count": tile_count,
        "estimated_bytes": tile_count * estimated_tile_bytes,
    }


def _fetch_tile(
    url: str,
    *,
    headers: Mapping[str, str],
    fetch_tile: TileFetch | None,
) -> bytes:
    if fetch_tile is not None:
        result = fetch_tile(url, headers)
        return result[0] if isinstance(result, tuple) else result
    request = urllib.request.Request(url, headers=dict(headers), method="GET")
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read()


def _seed_summary(
    status: str,
    *,
    plan: Mapping[str, Any],
    dry_run: bool,
    tiles_seen: int,
    tiles_written: int,
    tiles_skipped_existing: int,
    bytes_written: int,
    started_at: float,
) -> dict[str, Any]:
    return {
        "artifact_kind": "admin_tile_cache_seed_summary",
        "status": status,
        "plan_id": plan["plan_id"],
        "cache_root": plan["cache_root"],
        "dry_run": dry_run,
        "tiles_seen": tiles_seen,
        "tiles_written": tiles_written,
        "tiles_skipped_existing": tiles_skipped_existing,
        "bytes_written": bytes_written,
        "elapsed_seconds": round(time.time() - started_at, 3),
        "repo_fixture_write_allowed": False,
        "downloads_tiles_into_repo": False,
    }


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    raise SystemExit(main())
