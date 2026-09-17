from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from scout_contextual_permission_rudy import (
    render_daily_rudy_background,
    rudy_cache_settings,
)


def _write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _workspace(root: Path) -> tuple[dict, dict, dict]:
    project_id = "permission-rudy"
    cache_root = root / "cache"
    plan = {
        "project_id": project_id,
        "layer_id": "rudy-twmap",
        "source_id": "happyman_rudy_twmap",
        "cache_root": str(cache_root),
        "min_zoom": 5,
        "max_zoom": 5,
    }
    manifest = {
        "project_id": project_id,
        "layer_id": "rudy-twmap",
        "imagery_source_id": "happyman_rudy_twmap",
        "plan": plan,
    }
    bundle = {
        "project_id": project_id,
        "cache_root": str(cache_root),
        "layer_manifest_refs": {"rudy-twmap": "manifests/rudy.json"},
        "layer_source_ids": {"rudy-twmap": "happyman_rudy_twmap"},
    }
    project = {
        "project_id": project_id,
        "imagery_tile_cache_source_id": "nlsc_photo2",
        "imagery_tile_cache_root": str(cache_root),
        "workspace_raster_tile_cache_bundle_ref": "manifests/bundle.json",
    }
    _write(root / "project.json", project)
    _write(root / "manifests/bundle.json", bundle)
    _write(root / "manifests/rudy.json", manifest)
    for layer, color in [("rudy-twmap", (57, 79, 61)), ("imagery", (255, 0, 255))]:
        tile = cache_root / project_id / layer / "5/26/13.png"
        tile.parent.mkdir(parents=True)
        Image.new("RGB", (256, 256), color).save(tile)
    return project, bundle, manifest


def _hashes(root: Path) -> dict[str, str]:
    return {
        str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in root.rglob("*")
        if path.is_file()
    }


def test_dedicated_rudy_cache_renders_without_using_aerial_or_writing(tmp_path: Path) -> None:
    _workspace(tmp_path)
    before = _hashes(tmp_path)
    settings = rudy_cache_settings(tmp_path)
    assert settings.layer_id == "rudy-twmap"
    result = render_daily_rudy_background(
        project_id="permission-rudy",
        context=SimpleNamespace(route_points=[SimpleNamespace(lon=120.95, lat=23.55)]),
        cache_settings=settings,
        west=120.925, south=23.50, east=120.985, north=23.565,
    )
    with Image.open(io.BytesIO(result.body)) as image:
        assert image.size == (760, 248)
        assert image.getpixel((380, 124)) == (57, 79, 61)
    assert result.headers()["X-Scout-Imagery-Source-Id"] == "happyman_rudy_twmap"
    assert result.headers()["X-Scout-Writes-Performed"] == "false"
    assert _hashes(tmp_path) == before


@pytest.mark.parametrize(
    ("target", "field", "value"),
    [
        ("bundle", "project_id", "other-project"),
        ("bundle", "layer_source_ids", {"rudy-twmap": "nlsc_photo2"}),
        ("manifest", "project_id", "other-project"),
        ("manifest", "layer_id", "imagery"),
        ("manifest", "imagery_source_id", "nlsc_photo2"),
        ("plan", "source_id", "nlsc_photo2"),
        ("plan", "project_id", "other-project"),
        ("plan", "layer_id", "imagery"),
        ("plan", "cache_root", "/different-cache"),
    ],
)
def test_dedicated_rudy_rejects_inconsistent_provenance(
    tmp_path: Path, target: str, field: str, value: object,
) -> None:
    _, bundle, manifest = _workspace(tmp_path)
    {"bundle": bundle, "manifest": manifest, "plan": manifest["plan"]}[target][field] = value
    _write(tmp_path / "manifests/bundle.json", bundle)
    _write(tmp_path / "manifests/rudy.json", manifest)
    with pytest.raises(ValueError):
        rudy_cache_settings(tmp_path)


@pytest.mark.parametrize("ref", ["../rudy.json", "/tmp/rudy.json"])
def test_rudy_manifest_ref_cannot_escape_workspace(tmp_path: Path, ref: str) -> None:
    _, bundle, _ = _workspace(tmp_path)
    bundle["layer_manifest_refs"]["rudy-twmap"] = ref
    _write(tmp_path / "manifests/bundle.json", bundle)
    with pytest.raises(ValueError, match="escapes the workspace"):
        rudy_cache_settings(tmp_path)


def test_legacy_rudy_imagery_cache_remains_supported(tmp_path: Path) -> None:
    project, _, _ = _workspace(tmp_path)
    project.pop("workspace_raster_tile_cache_bundle_ref")
    project["imagery_tile_cache_source_id"] = "happyman_rudy_twmap"
    _write(tmp_path / "project.json", project)
    assert rudy_cache_settings(tmp_path).layer_id == "imagery"


def test_aerial_cache_without_a_dedicated_rudy_manifest_stays_unavailable(tmp_path: Path) -> None:
    project, _, _ = _workspace(tmp_path)
    project.pop("workspace_raster_tile_cache_bundle_ref")
    _write(tmp_path / "project.json", project)
    with pytest.raises(ValueError, match="not the reviewed imagery cache source"):
        rudy_cache_settings(tmp_path)
