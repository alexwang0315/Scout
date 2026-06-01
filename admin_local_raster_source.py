from __future__ import annotations

import argparse
import hashlib
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any


MODEL_PIXEL_SCALE_TAG = 33550
MODEL_TIEPOINT_TAG = 33922
GEO_KEY_DIRECTORY_TAG = 34735
GEO_ASCII_PARAMS_TAG = 34737
COMPRESSION_TAG = 259

GEOKEY_GT_MODEL_TYPE = 1024
GEOKEY_GTRASTER_TYPE = 1025
GEOKEY_GEOGRAPHIC_TYPE = 2048
GEOKEY_GEOG_CITATION = 2049

EPSG_WGS84 = 4326

DEFAULT_LOCAL_RASTER_CACHE_ROOT = Path("~/.cache/scout-fusion/raster-sources")
DEFAULT_PROJECT_ID = "chilai_nanhua_day1"
DEFAULT_LAYER_ID = "imagery"
ORDERING_POLICY = "imagery_bottom_api_top"


def build_local_raster_source_manifest(
    source_geotiff: Path | str,
    *,
    project_id: str = DEFAULT_PROJECT_ID,
    layer_id: str = DEFAULT_LAYER_ID,
    recommended_cache_root: Path | str = DEFAULT_LOCAL_RASTER_CACHE_ROOT,
    runtime_source_path: Path | str | None = None,
) -> dict[str, Any]:
    path = Path(source_geotiff).expanduser()
    if not path.exists():
        raise FileNotFoundError(path)
    if path.suffix.lower() not in {".tif", ".tiff", ".geotiff"}:
        raise ValueError("source_geotiff must be a GeoTIFF/TIFF file")

    image_metadata = _read_tiff_metadata(path)
    georef = _extract_wgs84_georeference(image_metadata)
    file_stat = path.stat()
    placement = _placement_advice(path)
    source_path = Path(runtime_source_path).expanduser() if runtime_source_path else path

    return {
        "artifact_kind": "admin_local_raster_source_manifest",
        "manifest_id": f"admin.local_raster.{project_id}.{path.stem}.v0",
        "project_id": project_id,
        "layer_id": layer_id,
        "layer_kind": "imagery",
        "ordering_policy": ORDERING_POLICY,
        "render_mode": "local_geotiff_source_manifest",
        "source_kind": "local_geotiff",
        "source_file": {
            "path": str(source_path),
            "filename": path.name,
            "size_bytes": file_stat.st_size,
            "sha256": _sha256(path),
            "storage_scope": (
                "mac_to_scout_handoff" if runtime_source_path else "local_cache_only"
            ),
            "repo_fixture_write_allowed": False,
            "raw_raster_committed_to_repo_allowed": False,
            **(
                {"mac_build_path": str(path)}
                if runtime_source_path and Path(runtime_source_path).expanduser() != path
                else {}
            ),
        },
        "image": {
            "format": image_metadata["format"],
            "mode": image_metadata["mode"],
            "width_px": image_metadata["width_px"],
            "height_px": image_metadata["height_px"],
            "compression": image_metadata["compression"],
        },
        "georeference": georef,
        "placement": placement,
        "recommended_cache_root": str(Path(recommended_cache_root).expanduser()),
        "external_network_required": False,
        "tile_cutting_performed": False,
        "derived_tiles_written": False,
        "notes_zh": [
            "這是本機 GeoTIFF 來源清單，不是 repo fixture，也不是 OSM tile 下載結果。",
            "目前只抽取 metadata 與 bbox；之後若要離線瀏覽，可再做 raster tile cutting。",
        ],
    }


def write_local_raster_source_manifest(
    manifest: Mapping[str, Any],
    path: Path | str,
) -> Path:
    output_path = Path(path).expanduser()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(dict(manifest), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return output_path


def _read_tiff_metadata(path: Path) -> dict[str, Any]:
    try:
        from PIL import Image
    except Exception as exc:  # pragma: no cover - environment guard
        raise RuntimeError("Pillow is required to inspect GeoTIFF metadata") from exc

    with Image.open(path) as image:
        tags = dict(getattr(image, "tag_v2", {}))
        return {
            "format": image.format,
            "mode": image.mode,
            "width_px": int(image.width),
            "height_px": int(image.height),
            "compression": _compression_name(tags.get(COMPRESSION_TAG)),
            "tags": tags,
        }


def _extract_wgs84_georeference(image_metadata: Mapping[str, Any]) -> dict[str, Any]:
    tags = image_metadata["tags"]
    geo_keys = _parse_geo_key_directory(tags.get(GEO_KEY_DIRECTORY_TAG))
    epsg_code = geo_keys.get(GEOKEY_GEOGRAPHIC_TYPE)
    citation = tags.get(GEO_ASCII_PARAMS_TAG)
    pixel_scale = tags.get(MODEL_PIXEL_SCALE_TAG)
    tiepoint = tags.get(MODEL_TIEPOINT_TAG)
    width = int(image_metadata["width_px"])
    height = int(image_metadata["height_px"])

    if not pixel_scale or not tiepoint or len(pixel_scale) < 2 or len(tiepoint) < 6:
        return {
            "status": "missing_geotiff_tags",
            "crs": _crs_payload(epsg_code, citation),
            "bbox_wgs84": None,
        }
    if epsg_code != EPSG_WGS84:
        return {
            "status": "unsupported_crs",
            "crs": _crs_payload(epsg_code, citation),
            "bbox_wgs84": None,
            "raw_tiepoint": list(tiepoint[:6]),
            "raw_pixel_scale": list(pixel_scale[:3]),
        }

    scale_x = float(pixel_scale[0])
    scale_y = float(pixel_scale[1])
    tie_pixel_x = float(tiepoint[0])
    tie_pixel_y = float(tiepoint[1])
    tie_lon = float(tiepoint[3])
    tie_lat = float(tiepoint[4])
    west = tie_lon - tie_pixel_x * scale_x
    north = tie_lat + tie_pixel_y * scale_y
    east = west + width * scale_x
    south = north - height * scale_y

    return {
        "status": "geotiff_wgs84",
        "crs": _crs_payload(epsg_code, citation),
        "tiepoint_wgs84": {
            "pixel_x": tie_pixel_x,
            "pixel_y": tie_pixel_y,
            "lon": tie_lon,
            "lat": tie_lat,
        },
        "pixel_scale_degrees": {
            "lon_per_pixel": scale_x,
            "lat_per_pixel": scale_y,
        },
        "bbox_wgs84": {
            "south": south,
            "west": west,
            "north": north,
            "east": east,
        },
    }


def _parse_geo_key_directory(raw: Any) -> dict[int, int]:
    if not raw or len(raw) < 4:
        return {}
    values = [int(item) for item in raw]
    key_count = values[3]
    keys: dict[int, int] = {}
    offset = 4
    for index in range(key_count):
        start = offset + index * 4
        if start + 3 >= len(values):
            break
        key_id, tiff_tag_location, count, value_offset = values[start : start + 4]
        if tiff_tag_location == 0 and count == 1:
            keys[key_id] = value_offset
    return keys


def _crs_payload(epsg_code: int | None, citation: Any) -> dict[str, Any]:
    return {
        "authority": "EPSG" if epsg_code else None,
        "code": epsg_code,
        "name": _clean_ascii_tag(citation),
    }


def _placement_advice(path: Path) -> dict[str, Any]:
    in_manifest_dir = path.parent.name == "manifests"
    return {
        "current_parent": str(path.parent),
        "in_manifest_directory": in_manifest_dir,
        "recommended_parent_kind": "raster_source_cache",
        "warning": (
            "GeoTIFF source files should preferably live outside manifests/; keep manifests/ for small JSON descriptors."
            if in_manifest_dir
            else None
        ),
    }


def _compression_name(raw: Any) -> str | None:
    names = {
        1: "none",
        5: "lzw",
        7: "jpeg",
        8: "deflate",
        32773: "packbits",
    }
    if raw is None:
        return None
    try:
        return names.get(int(raw), str(raw))
    except (TypeError, ValueError):
        return str(raw)


def _clean_ascii_tag(raw: Any) -> str | None:
    if raw is None:
        return None
    text = str(raw).strip()
    return text.rstrip("|") or None


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Build a Scout admin local GeoTIFF raster source manifest."
    )
    parser.add_argument("--source-geotiff", type=Path, required=True)
    parser.add_argument("--project-id", default=DEFAULT_PROJECT_ID)
    parser.add_argument("--layer-id", default=DEFAULT_LAYER_ID)
    parser.add_argument("--runtime-source-path", type=Path)
    parser.add_argument("--write-manifest", type=Path, required=True)
    args = parser.parse_args(argv)

    manifest = build_local_raster_source_manifest(
        args.source_geotiff,
        project_id=args.project_id,
        layer_id=args.layer_id,
        runtime_source_path=args.runtime_source_path,
    )
    output_path = write_local_raster_source_manifest(manifest, args.write_manifest)
    print(
        json.dumps(
            {
                "manifest": str(output_path),
                "status": manifest["georeference"]["status"],
                "bbox_wgs84": manifest["georeference"]["bbox_wgs84"],
                "size_bytes": manifest["source_file"]["size_bytes"],
                "tile_cutting_performed": manifest["tile_cutting_performed"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
