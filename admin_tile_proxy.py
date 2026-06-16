from __future__ import annotations

import hashlib
import io
from dataclasses import dataclass
from pathlib import Path
from typing import Any


DEFAULT_OSM_TILE_CACHE_ROOT = Path("~/.cache/scout-fusion/osm-tiles")
LOCAL_OSM_TILE_URL_TEMPLATE = "/admin/tiles/osm/{z}/{x}/{y}.png"
MAX_LOCAL_PROXY_ZOOM = 20
TRANSPARENT_PNG_TILE = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
    "0000000d49444154789c6360606060000000050001a5f645400000000049454e44"
    "ae426082"
)


@dataclass(frozen=True)
class AdminTilePayload:
    body: bytes
    media_type: str
    source: str
    cache_path: Path
    body_sha256: str

    def headers(self) -> dict[str, str]:
        cache_control = (
            "no-store"
            if self.source.endswith("_fallback")
            else "no-cache, max-age=0, must-revalidate"
        )
        return {
            "Cache-Control": cache_control,
            "X-Scout-Tile-Source": self.source,
            "X-Scout-Tile-Hash": self.body_sha256,
        }


def build_osm_tile_proxy_contract(
    *,
    cache_root: Path | str = DEFAULT_OSM_TILE_CACHE_ROOT,
    fallback_enabled: bool = True,
) -> dict[str, Any]:
    root = Path(cache_root).expanduser()
    return {
        "artifact_kind": "admin_osm_tile_proxy_contract",
        "status": "local_proxy_ready",
        "url_template": LOCAL_OSM_TILE_URL_TEMPLATE,
        "cache_root": str(root),
        "cache_policy": "local_file_cache_then_offline_fallback",
        "fallback_enabled": fallback_enabled,
        "external_network_fetch_allowed": False,
        "downloads_tiles_into_repo": False,
        "max_zoom": MAX_LOCAL_PROXY_ZOOM,
        "notes": [
            "Proxy serves cached local OSM tiles when present.",
            "When fallback is enabled, missing tiles return a plain offline diagnostic SVG tile.",
            "This helper never fetches public OSM tile URLs; pre-seeding cache is a separate operator action.",
        ],
    }


def osm_tile_cache_path(
    z: int | str,
    x: int | str,
    y: int | str,
    *,
    cache_root: Path | str = DEFAULT_OSM_TILE_CACHE_ROOT,
) -> Path:
    tile = validate_osm_tile_coords(z, x, y)
    return Path(cache_root).expanduser() / str(tile["z"]) / str(tile["x"]) / f"{tile['y']}.png"


def load_or_build_osm_tile_payload(
    z: int | str,
    x: int | str,
    y: int | str,
    *,
    cache_root: Path | str = DEFAULT_OSM_TILE_CACHE_ROOT,
    fallback_enabled: bool = True,
    fallback_style: str = "offline",
) -> AdminTilePayload:
    cache_path = osm_tile_cache_path(z, x, y, cache_root=cache_root)
    if cache_path.exists():
        body = cache_path.read_bytes()
        return AdminTilePayload(
            body=body,
            media_type="image/png",
            source="local_cache",
            cache_path=cache_path,
            body_sha256=hashlib.sha256(body).hexdigest(),
        )
    parent_payload = _parent_cache_tile_payload(
        z,
        x,
        y,
        cache_root=cache_root,
        requested_cache_path=cache_path,
    )
    if parent_payload is not None:
        return parent_payload
    if not fallback_enabled:
        raise FileNotFoundError(str(cache_path))

    tile = validate_osm_tile_coords(z, x, y)
    source = "offline_fallback"
    body = _offline_svg_tile(tile["z"], tile["x"], tile["y"])
    if fallback_style == "transparent":
        source = "transparent_fallback"
        body = _transparent_png_tile()
    return AdminTilePayload(
        body=body,
        media_type="image/png" if fallback_style == "transparent" else "image/svg+xml",
        source=source,
        cache_path=cache_path,
        body_sha256=hashlib.sha256(body).hexdigest(),
    )


def _parent_cache_tile_payload(
    z: int | str,
    x: int | str,
    y: int | str,
    *,
    cache_root: Path | str,
    requested_cache_path: Path,
) -> AdminTilePayload | None:
    tile = validate_osm_tile_coords(z, x, y)
    for parent_z in range(tile["z"] - 1, -1, -1):
        scale = 2 ** (tile["z"] - parent_z)
        parent_x = tile["x"] // scale
        parent_y = tile["y"] // scale
        parent_path = osm_tile_cache_path(
            parent_z,
            parent_x,
            parent_y,
            cache_root=cache_root,
        )
        if not parent_path.exists():
            continue
        parent_body = parent_path.read_bytes()
        body = _crop_parent_tile_to_child(
            parent_body,
            child_x=tile["x"] - parent_x * scale,
            child_y=tile["y"] - parent_y * scale,
            scale=scale,
        )
        if body is None:
            continue
        return AdminTilePayload(
            body=body,
            media_type="image/png",
            source="local_parent_cache_fallback",
            cache_path=requested_cache_path,
            body_sha256=hashlib.sha256(body).hexdigest(),
        )
    return None


def _crop_parent_tile_to_child(
    body: bytes,
    *,
    child_x: int,
    child_y: int,
    scale: int,
) -> bytes | None:
    try:
        from PIL import Image
    except Exception:  # pragma: no cover - optional runtime dependency
        return None
    try:
        with Image.open(io.BytesIO(body)) as image:
            parent = image.convert("RGBA")
            width, height = parent.size
            left = int(round(child_x * width / scale))
            upper = int(round(child_y * height / scale))
            right = int(round((child_x + 1) * width / scale))
            lower = int(round((child_y + 1) * height / scale))
            if right <= left or lower <= upper:
                return None
            crop = parent.crop((left, upper, right, lower))
            resample = getattr(getattr(Image, "Resampling", Image), "BICUBIC")
            resized = crop.resize((width, height), resample=resample)
            output = io.BytesIO()
            resized.save(output, format="PNG")
            return output.getvalue()
    except Exception:
        return None


def validate_osm_tile_coords(
    z: int | str,
    x: int | str,
    y: int | str,
) -> dict[str, int]:
    try:
        z_int = int(z)
        x_int = int(x)
        y_int = int(y)
    except (TypeError, ValueError) as exc:
        raise ValueError("tile coordinates must be integers") from exc

    if z_int < 0 or z_int > MAX_LOCAL_PROXY_ZOOM:
        raise ValueError(f"tile z must be between 0 and {MAX_LOCAL_PROXY_ZOOM}")
    max_index = (2**z_int) - 1
    if x_int < 0 or x_int > max_index:
        raise ValueError(f"tile x must be between 0 and {max_index} for z={z_int}")
    if y_int < 0 or y_int > max_index:
        raise ValueError(f"tile y must be between 0 and {max_index} for z={z_int}")
    return {"z": z_int, "x": x_int, "y": y_int}


def _offline_svg_tile(z: int, x: int, y: int) -> bytes:
    text = f"OSM offline {z}/{x}/{y}"
    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="256" height="256" viewBox="0 0 256 256">
  <rect width="256" height="256" fill="#f4f7f8"/>
  <rect x="0.5" y="0.5" width="255" height="255" fill="none" stroke="#c8d3da" stroke-width="1"/>
  <text x="128" y="132" text-anchor="middle" font-family="system-ui, -apple-system, sans-serif" font-size="15" fill="#536575">{text}</text>
</svg>
"""
    return svg.encode("utf-8")


def _transparent_png_tile() -> bytes:
    return TRANSPARENT_PNG_TILE
