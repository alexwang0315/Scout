from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any


DEFAULT_OSM_TILE_CACHE_ROOT = Path("~/.cache/scout-fusion/osm-tiles")
LOCAL_OSM_TILE_URL_TEMPLATE = "/admin/tiles/osm/{z}/{x}/{y}.png"
MAX_LOCAL_PROXY_ZOOM = 20


@dataclass(frozen=True)
class AdminTilePayload:
    body: bytes
    media_type: str
    source: str
    cache_path: Path
    body_sha256: str

    def headers(self) -> dict[str, str]:
        return {
            "Cache-Control": "public, max-age=86400",
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
            "When fallback is enabled, missing tiles return a generated offline demo SVG tile.",
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
    if not fallback_enabled:
        raise FileNotFoundError(str(cache_path))

    tile = validate_osm_tile_coords(z, x, y)
    body = _offline_svg_tile(tile["z"], tile["x"], tile["y"])
    return AdminTilePayload(
        body=body,
        media_type="image/svg+xml",
        source="offline_fallback",
        cache_path=cache_path,
        body_sha256=hashlib.sha256(body).hexdigest(),
    )


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
    hue = (x * 37 + y * 17 + z * 11) % 360
    accent = f"hsl({hue}, 32%, 44%)"
    text = f"OSM offline {z}/{x}/{y}"
    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="256" height="256" viewBox="0 0 256 256">
  <rect width="256" height="256" fill="#d9e0dd"/>
  <path d="M0 64H256M0 128H256M0 192H256M64 0V256M128 0V256M192 0V256" stroke="#aeb9b4" stroke-width="2"/>
  <path d="M-20 190C48 146 94 157 143 109C184 68 213 66 276 38" fill="none" stroke="{accent}" stroke-width="18" stroke-linecap="round" opacity="0.72"/>
  <path d="M-14 204C54 160 101 170 151 121C191 82 220 79 282 52" fill="none" stroke="#f5f7f2" stroke-width="5" stroke-linecap="round" opacity="0.88"/>
  <text x="128" y="238" text-anchor="middle" font-family="system-ui, -apple-system, sans-serif" font-size="17" fill="#26302d">{text}</text>
</svg>
"""
    return svg.encode("utf-8")
