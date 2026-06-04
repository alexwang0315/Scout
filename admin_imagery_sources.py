from __future__ import annotations

import hashlib
import json
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from admin_tile_proxy import validate_osm_tile_coords


DEFAULT_IMAGERY_SOURCE_ID = "nlsc_photo2"
DEFAULT_REGISTRY_ID = "scout.imagery_sources.default.v1"
DEFAULT_TILE_FETCH_TIMEOUT_SECONDS = 10.0
HAPPYMAN_WMTS_ENDPOINT = "https://tile.happyman.idv.tw/mp/service"
HAPPYMAN_WMTS_TILE_MATRIX_SET = "gm_grid"


def _happyman_wmts_metadata(layer_id: str) -> dict[str, Any]:
    return {
        "wmts_endpoint": HAPPYMAN_WMTS_ENDPOINT,
        "wmts_layer": layer_id,
        "wmts_style": "default",
        "wmts_tile_matrix_set": HAPPYMAN_WMTS_TILE_MATRIX_SET,
        "wmts_tile_matrix_id_style": "zero_padded_2",
        "wmts_format": "image/png",
        "wmts_version": "1.0.0",
        "tile_matrix_crs": "EPSG:3857",
        "tile_pyramid_kind": "web_mercator_slippy_compatible",
    }


DEFAULT_IMAGERY_SOURCE_REGISTRY: dict[str, Any] = {
    "artifact_kind": "scout_imagery_source_registry",
    "schema_version": "1.0",
    "registry_id": DEFAULT_REGISTRY_ID,
    "default_source_id": DEFAULT_IMAGERY_SOURCE_ID,
    "sources": {
        "nlsc_photo2": {
            "source_id": "nlsc_photo2",
            "label": "NLSC PHOTO2",
            "label_zh": "內政部國土測量中心正射影像 PHOTO2",
            "provider": "NLSC",
            "source_kind": "wmts_tile",
            "url_template": (
                "https://wmts.nlsc.gov.tw/wmts/PHOTO2/default/"
                "EPSG:3857/{z}/{y}/{x}"
            ),
            "tile_order": "z_y_x",
            "media_type": "image/png",
            "min_zoom": 5,
            "max_zoom": 19,
            "attribution": "NLSC",
            "cache_policy": "local_cache_then_remote_fetch_when_explicit",
            "requires_explicit_remote_fetch": True,
            "notes_zh": [
                "NLSC WMTS 圖磚順序是 z/y/x，不是一般 z/x/y。",
                "Scout 只透過 allowlist source 呼叫，不接受任意外部 URL。",
            ],
        },
        "nlsc_photo_mix": {
            "source_id": "nlsc_photo_mix",
            "label": "NLSC PHOTO MIX",
            "label_zh": "內政部國土測量中心正射混合影像",
            "provider": "NLSC",
            "source_kind": "wmts_tile",
            "url_template": (
                "https://wmts.nlsc.gov.tw/wmts/PHOTO_MIX/default/"
                "EPSG:3857/{z}/{y}/{x}"
            ),
            "tile_order": "z_y_x",
            "media_type": "image/png",
            "min_zoom": 5,
            "max_zoom": 19,
            "attribution": "NLSC",
            "cache_policy": "local_cache_then_remote_fetch_when_explicit",
            "requires_explicit_remote_fetch": True,
            "notes_zh": [
                "NLSC PHOTO_MIX WMTS 圖磚順序是 z/y/x。",
            ],
        },
        "happyman_atis": {
            "source_id": "happyman_atis",
            "label": "Happyman ATIS",
            "label_zh": "Happyman 農航所正射影像 cache",
            "provider": "Happyman / ATIS",
            "source_kind": "xyz_tile",
            "url_template": "https://tile.happyman.idv.tw/map/atis/{z}/{x}/{y}.png",
            "tile_order": "z_x_y",
            "media_type": "image/png",
            "min_zoom": 5,
            "max_zoom": 20,
            "attribution": "台灣歷史百年地圖 / 農航所正射影像",
            "cache_policy": "local_cache_then_remote_fetch_when_explicit",
            "requires_explicit_remote_fetch": True,
            "notes_zh": [
                "Happyman cache 多數為 z/x/y；不可與 NLSC z/y/x 混用。",
            ],
        },
        "happyman_rudy": {
            "source_id": "happyman_rudy",
            "label": "Rudy Map",
            "label_zh": "魯地圖",
            "provider": "Happyman / Rudy Map",
            "source_kind": "wmts_kvp_tile",
            **_happyman_wmts_metadata("rudy"),
            "url_template": (
                "https://tile.happyman.idv.tw/mp/service?"
                "SERVICE=WMTS&REQUEST=GetTile&VERSION=1.0.0"
                "&LAYER=rudy&STYLE=default&TILEMATRIXSET=gm_grid"
                "&TILEMATRIX={z}&TILEROW={y}&TILECOL={x}&FORMAT=image/png"
            ),
            "tile_order": "wmts_kvp_z_y_x",
            "media_type": "image/png",
            "min_zoom": 5,
            "max_zoom": 20,
            "attribution": "魯地圖 / Happyman WMTS",
            "cache_policy": "local_cache_then_remote_fetch_when_explicit",
            "requires_explicit_remote_fetch": True,
            "notes_zh": [
                "魯地圖 Rudy Map 作為登山地形底圖使用；Scout 只透過 allowlist proxy/cache 呼叫。",
                "WMTS KVP 參數使用 TILEMATRIX={z}, TILEROW={y}, TILECOL={x}。",
            ],
        },
        "happyman_rudy_twmap": {
            "source_id": "happyman_rudy_twmap",
            "label": "Rudy Map + TWMap",
            "label_zh": "魯地圖 + TWMap style",
            "provider": "Happyman / Rudy Map",
            "source_kind": "wmts_kvp_tile",
            **_happyman_wmts_metadata("rudy_twmap"),
            "url_template": (
                "https://tile.happyman.idv.tw/mp/service?"
                "SERVICE=WMTS&REQUEST=GetTile&VERSION=1.0.0"
                "&LAYER=rudy_twmap&STYLE=default&TILEMATRIXSET=gm_grid"
                "&TILEMATRIX={z}&TILEROW={y}&TILECOL={x}&FORMAT=image/png"
            ),
            "tile_order": "wmts_kvp_z_y_x",
            "media_type": "image/png",
            "min_zoom": 5,
            "max_zoom": 20,
            "attribution": "魯地圖 / Happyman WMTS",
            "cache_policy": "local_cache_then_remote_fetch_when_explicit",
            "requires_explicit_remote_fetch": True,
            "notes_zh": [
                "魯地圖加 TWMap style，適合與正射影像做比較。",
            ],
        },
        "happyman_colorrelief": {
            "source_id": "happyman_colorrelief",
            "label": "Taiwan color relief",
            "label_zh": "台灣山坡陰影",
            "provider": "Happyman WMTS",
            "source_kind": "wmts_kvp_tile",
            **_happyman_wmts_metadata("colorrelief"),
            "url_template": (
                "https://tile.happyman.idv.tw/mp/service?"
                "SERVICE=WMTS&REQUEST=GetTile&VERSION=1.0.0"
                "&LAYER=colorrelief&STYLE=default&TILEMATRIXSET=gm_grid"
                "&TILEMATRIX={z}&TILEROW={y}&TILECOL={x}&FORMAT=image/png"
            ),
            "tile_order": "wmts_kvp_z_y_x",
            "media_type": "image/png",
            "min_zoom": 5,
            "max_zoom": 20,
            "attribution": "Happyman WMTS",
            "cache_policy": "local_cache_then_remote_fetch_when_explicit",
            "requires_explicit_remote_fetch": True,
            "notes_zh": [
                "山坡陰影 relief overlay（地形陰影覆蓋層），只作 pretrip visual context。",
            ],
        },
        "happyman_geo2016": {
            "source_id": "happyman_geo2016",
            "label": "Taiwan geology 2016",
            "label_zh": "台灣地質圖 2016",
            "provider": "Happyman WMTS",
            "source_kind": "wmts_kvp_tile",
            **_happyman_wmts_metadata("geo2016"),
            "url_template": (
                "https://tile.happyman.idv.tw/mp/service?"
                "SERVICE=WMTS&REQUEST=GetTile&VERSION=1.0.0"
                "&LAYER=geo2016&STYLE=default&TILEMATRIXSET=gm_grid"
                "&TILEMATRIX={z}&TILEROW={y}&TILECOL={x}&FORMAT=image/png"
            ),
            "tile_order": "wmts_kvp_z_y_x",
            "media_type": "image/png",
            "min_zoom": 5,
            "max_zoom": 20,
            "attribution": "Happyman WMTS / Taiwan geology 2016",
            "cache_policy": "local_cache_then_remote_fetch_when_explicit",
            "requires_explicit_remote_fetch": True,
            "notes_zh": [
                "地質圖 geology overlay（地質覆蓋層），不直接成為 runtime safety truth。",
            ],
        },
        "happyman_tw5k2000": {
            "source_id": "happyman_tw5k2000",
            "label": "Taiwan 1/5000 topo",
            "label_zh": "台灣 1/5000 地形圖",
            "provider": "Happyman WMTS",
            "source_kind": "wmts_kvp_tile",
            **_happyman_wmts_metadata("tw5k2000"),
            "url_template": (
                "https://tile.happyman.idv.tw/mp/service?"
                "SERVICE=WMTS&REQUEST=GetTile&VERSION=1.0.0"
                "&LAYER=tw5k2000&STYLE=default&TILEMATRIXSET=gm_grid"
                "&TILEMATRIX={z}&TILEROW={y}&TILECOL={x}&FORMAT=image/png"
            ),
            "tile_order": "wmts_kvp_z_y_x",
            "media_type": "image/png",
            "min_zoom": 5,
            "max_zoom": 20,
            "attribution": "Happyman WMTS",
            "cache_policy": "local_cache_then_remote_fetch_when_explicit",
            "requires_explicit_remote_fetch": True,
            "notes_zh": [
                "1/5000 topo map（地形圖）可作登山細節參考。",
            ],
        },
        "happyman_forest": {
            "source_id": "happyman_forest",
            "label": "Taiwan forest compartments",
            "label_zh": "台灣林班界",
            "provider": "Happyman WMTS",
            "source_kind": "wmts_kvp_tile",
            **_happyman_wmts_metadata("forest"),
            "url_template": (
                "https://tile.happyman.idv.tw/mp/service?"
                "SERVICE=WMTS&REQUEST=GetTile&VERSION=1.0.0"
                "&LAYER=forest&STYLE=default&TILEMATRIXSET=gm_grid"
                "&TILEMATRIX={z}&TILEROW={y}&TILECOL={x}&FORMAT=image/png"
            ),
            "tile_order": "wmts_kvp_z_y_x",
            "media_type": "image/png",
            "min_zoom": 5,
            "max_zoom": 20,
            "attribution": "Happyman WMTS",
            "cache_policy": "local_cache_then_remote_fetch_when_explicit",
            "requires_explicit_remote_fetch": True,
            "notes_zh": [
                "林班界 forest compartment overlay（林班界覆蓋層），供 pretrip context 使用。",
            ],
        },
    },
}


@dataclass(frozen=True)
class RemoteImageryTile:
    body: bytes
    media_type: str
    source_id: str
    url: str
    body_sha256: str


def build_imagery_source_registry_contract(
    *,
    registry_path: Path | str | None = None,
) -> dict[str, Any]:
    registry = load_imagery_source_registry(registry_path)
    return {
        "artifact_kind": "scout_imagery_source_registry_contract",
        "status": "registry_ready",
        "registry_id": registry["registry_id"],
        "default_source_id": registry["default_source_id"],
        "source_count": len(registry["sources"]),
        "sources": [
            _source_public_contract(source)
            for source in registry["sources"].values()
        ],
        "remote_fetch_requires_explicit_enable": True,
        "remote_fetch_env": "SCOUT_ADMIN_IMAGERY_REMOTE_FETCH",
        "registry_path_env": "SCOUT_IMAGERY_SOURCE_REGISTRY_PATH",
        "notes_zh": [
            "Scout imagery source（影像來源）由 allowlist registry 管理。",
            "UI 呼叫 Scout proxy；proxy 再依 registry 與 cache policy 決定是否抓遠端圖磚。",
        ],
    }


def load_imagery_source_registry(
    registry_path: Path | str | None = None,
) -> dict[str, Any]:
    registry = json.loads(json.dumps(DEFAULT_IMAGERY_SOURCE_REGISTRY))
    if registry_path:
        path = Path(registry_path).expanduser()
        if path.exists():
            custom = json.loads(path.read_text(encoding="utf-8"))
            registry = _merge_registry(registry, custom)
    _validate_registry(registry)
    return registry


def imagery_source_for_project(
    project: Mapping[str, Any] | None,
    *,
    layer_id: str = "imagery",
    registry_path: Path | str | None = None,
    source_id: str | None = None,
) -> dict[str, Any]:
    registry = load_imagery_source_registry(registry_path)
    resolved_source_id = source_id or _project_source_id(project or {}, layer_id=layer_id)
    if not resolved_source_id:
        resolved_source_id = str(registry["default_source_id"])
    source = registry["sources"].get(str(resolved_source_id))
    if not source:
        raise ValueError(f"unknown imagery source_id: {resolved_source_id}")
    return dict(source)


def imagery_tile_url(source: Mapping[str, Any], z: int, x: int, y: int) -> str:
    tile = validate_osm_tile_coords(z, x, y)
    min_zoom = int(source.get("min_zoom", 0))
    max_zoom = int(source.get("max_zoom", 20))
    if tile["z"] < min_zoom or tile["z"] > max_zoom:
        raise ValueError(
            f"imagery source {source.get('source_id')} supports z {min_zoom}-{max_zoom}"
        )
    if source.get("source_kind") == "wmts_kvp_tile" and source.get("wmts_endpoint"):
        return _wmts_kvp_tile_url(source, tile)
    template = str(source.get("url_template") or "")
    if not template:
        raise ValueError("imagery source is missing url_template")
    return template.format(z=tile["z"], x=tile["x"], y=tile["y"])


def wmts_source_metadata(source: Mapping[str, Any]) -> dict[str, Any]:
    if source.get("source_kind") != "wmts_kvp_tile":
        return {}
    return {
        "wmts_endpoint_sha256": hashlib.sha256(
            str(source.get("wmts_endpoint") or "").encode("utf-8")
        ).hexdigest(),
        "wmts_layer": source.get("wmts_layer"),
        "wmts_style": source.get("wmts_style", "default"),
        "wmts_tile_matrix_set": source.get("wmts_tile_matrix_set"),
        "wmts_tile_matrix_id_style": source.get("wmts_tile_matrix_id_style"),
        "wmts_format": source.get("wmts_format", source.get("media_type", "image/png")),
        "wmts_version": source.get("wmts_version", "1.0.0"),
        "tile_matrix_crs": source.get("tile_matrix_crs"),
        "tile_pyramid_kind": source.get("tile_pyramid_kind"),
        "raw_wmts_endpoint_embedded": False,
    }


def fetch_remote_imagery_tile(
    source: Mapping[str, Any],
    z: int,
    x: int,
    y: int,
    *,
    timeout_seconds: float = DEFAULT_TILE_FETCH_TIMEOUT_SECONDS,
    opener: Callable[[str, float], tuple[bytes, str | None]] | None = None,
) -> RemoteImageryTile:
    url = imagery_tile_url(source, z, x, y)
    if opener is None:
        body, media_type = _urllib_fetch(url, timeout_seconds)
    else:
        body, media_type = opener(url, timeout_seconds)
    if not body:
        raise ValueError(f"empty imagery tile response for {url}")
    resolved_media_type = media_type or str(source.get("media_type") or "image/png")
    return RemoteImageryTile(
        body=body,
        media_type=resolved_media_type.split(";")[0].strip() or "image/png",
        source_id=str(source["source_id"]),
        url=url,
        body_sha256=hashlib.sha256(body).hexdigest(),
    )


def _urllib_fetch(url: str, timeout_seconds: float) -> tuple[bytes, str | None]:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Scout imagery proxy/alpha",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
        return response.read(), response.headers.get("Content-Type")


def _project_source_id(project: Mapping[str, Any], *, layer_id: str) -> str | None:
    layer_sources = project.get("imagery_sources")
    if isinstance(layer_sources, Mapping):
        layer_source = layer_sources.get(layer_id)
        if isinstance(layer_source, str):
            return layer_source
        if isinstance(layer_source, Mapping) and layer_source.get("source_id"):
            return str(layer_source["source_id"])
    value = project.get("imagery_source_id")
    return str(value) if value else None


def _merge_registry(base: dict[str, Any], custom: Mapping[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    if custom.get("registry_id"):
        merged["registry_id"] = str(custom["registry_id"])
    if custom.get("default_source_id"):
        merged["default_source_id"] = str(custom["default_source_id"])
    custom_sources = custom.get("sources")
    if isinstance(custom_sources, list):
        custom_sources = {
            str(source["source_id"]): source
            for source in custom_sources
            if isinstance(source, Mapping) and source.get("source_id")
        }
    if isinstance(custom_sources, Mapping):
        sources = dict(merged.get("sources") or {})
        for source_id, source in custom_sources.items():
            if isinstance(source, Mapping):
                source_copy = dict(source)
                source_copy.setdefault("source_id", str(source_id))
                sources[str(source_id)] = source_copy
        merged["sources"] = sources
    return merged


def _validate_registry(registry: Mapping[str, Any]) -> None:
    if registry.get("artifact_kind") != "scout_imagery_source_registry":
        raise ValueError("registry artifact_kind must be scout_imagery_source_registry")
    sources = registry.get("sources")
    if not isinstance(sources, Mapping) or not sources:
        raise ValueError("imagery source registry must contain sources")
    default_id = str(registry.get("default_source_id") or "")
    if default_id not in sources:
        raise ValueError("default_source_id must exist in sources")
    for source_id, source in sources.items():
        if not isinstance(source, Mapping):
            raise ValueError(f"source {source_id} must be an object")
        _validate_source(str(source_id), source)


def _validate_source(source_id: str, source: Mapping[str, Any]) -> None:
    declared_id = str(source.get("source_id") or "")
    if declared_id != source_id:
        raise ValueError(f"source_id mismatch for {source_id}")
    if not _safe_identifier(declared_id):
        raise ValueError(f"unsafe imagery source_id: {declared_id}")
    template = str(source.get("url_template") or "")
    if (
        source.get("source_kind") == "wmts_kvp_tile"
        and source.get("wmts_endpoint")
    ):
        for key in ("wmts_layer", "wmts_tile_matrix_set"):
            if not source.get(key):
                raise ValueError(f"source {source_id} is missing {key}")
        endpoint = str(source.get("wmts_endpoint") or "")
        if not endpoint.startswith(("https://", "http://")):
            raise ValueError(f"source {source_id} wmts_endpoint must be http(s)")
    elif "{z}" not in template or "{x}" not in template or "{y}" not in template:
        raise ValueError(f"source {source_id} url_template must contain z/x/y")
    if template and not template.startswith(("https://", "http://")):
        raise ValueError(f"source {source_id} url_template must be http(s)")
    min_zoom = int(source.get("min_zoom", 0))
    max_zoom = int(source.get("max_zoom", 20))
    if min_zoom < 0 or max_zoom > 20 or min_zoom > max_zoom:
        raise ValueError(f"source {source_id} zoom range must be within 0-20")


def _source_public_contract(source: Mapping[str, Any]) -> dict[str, Any]:
    contract = {
        "source_id": source["source_id"],
        "label": source.get("label"),
        "label_zh": source.get("label_zh"),
        "provider": source.get("provider"),
        "source_kind": source.get("source_kind"),
        "tile_order": source.get("tile_order"),
        "min_zoom": source.get("min_zoom"),
        "max_zoom": source.get("max_zoom"),
        "attribution": source.get("attribution"),
        "cache_policy": source.get("cache_policy"),
        "requires_explicit_remote_fetch": bool(
            source.get("requires_explicit_remote_fetch", True)
        ),
        "url_template_sha256": hashlib.sha256(
            str(source.get("url_template") or "").encode("utf-8")
        ).hexdigest(),
    }
    contract.update(wmts_source_metadata(source))
    return contract


def _wmts_kvp_tile_url(source: Mapping[str, Any], tile: Mapping[str, int]) -> str:
    endpoint = str(source.get("wmts_endpoint") or "").strip()
    if not endpoint:
        raise ValueError("WMTS source is missing wmts_endpoint")
    query = {
        "SERVICE": "WMTS",
        "REQUEST": "GetTile",
        "VERSION": str(source.get("wmts_version") or "1.0.0"),
        "LAYER": str(source.get("wmts_layer") or ""),
        "STYLE": str(source.get("wmts_style") or "default"),
        "TILEMATRIXSET": str(source.get("wmts_tile_matrix_set") or ""),
        "TILEMATRIX": _wmts_tile_matrix_id(source, int(tile["z"])),
        "TILEROW": str(int(tile["y"])),
        "TILECOL": str(int(tile["x"])),
        "FORMAT": str(source.get("wmts_format") or source.get("media_type") or "image/png"),
    }
    if not query["LAYER"] or not query["TILEMATRIXSET"]:
        raise ValueError("WMTS source is missing layer or TileMatrixSet")
    separator = "&" if "?" in endpoint else "?"
    return endpoint + separator + urllib.parse.urlencode(query)


def _wmts_tile_matrix_id(source: Mapping[str, Any], z: int) -> str:
    style = str(source.get("wmts_tile_matrix_id_style") or "plain")
    if style == "zero_padded_2":
        return f"{z:02d}"
    return str(z)


def _safe_identifier(value: str) -> bool:
    allowed = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_.-")
    return bool(value) and ".." not in value and all(char in allowed for char in value)
