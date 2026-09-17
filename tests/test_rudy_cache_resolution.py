"""Rudy detail requests must prove an exact cached tile without network effects."""

import io
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from admin_api import create_admin_app
from admin_imagery_sources import imagery_source_for_project
from admin_local_raster_tiles import (
    TRANSPARENT_PNG_TILE,
    imagery_source_raster_tile_cache_path,
    load_or_build_raster_tile_payload,
    raster_tile_cache_path,
)


PROJECT = "dongqing_cache_test"
SOURCE_ID = "happyman_rudy_twmap"
TILE = (16, 54772, 28300)


def _tile_png() -> bytes:
    image = Image.new("RGB", (256, 256), "#e4ecbb")
    image.paste("#347244", (128, 0, 256, 256))
    output = io.BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def _write(path: Path, body: bytes | None = None) -> bytes:
    path.parent.mkdir(parents=True, exist_ok=True)
    body = _tile_png() if body is None else body
    path.write_bytes(body)
    return body


def _url(layer="rudy-twmap", *, query="cache_only=1&exact=1") -> str:
    z, x, y = TILE
    return (
        f"/admin/tiles/imagery/{PROJECT}/{layer}/{z}/{x}/{y}.png"
        f"?source_id={SOURCE_ID}&{query}"
    )


@pytest.fixture
def cache_client(tmp_path, monkeypatch):
    monkeypatch.setenv("SCOUT_ADMIN_RASTER_TILE_CACHE_ROOT", str(tmp_path))
    # A global opt-in must not override the per-request read-only policy.
    monkeypatch.setenv("SCOUT_ADMIN_IMAGERY_REMOTE_FETCH", "true")
    monkeypatch.setenv("SCOUT_ADMIN_RASTER_TILE_FALLBACK", "true")
    monkeypatch.delenv("SCOUT_IMAGERY_SOURCE_REGISTRY_PATH", raising=False)

    def forbidden_network(*_args, **_kwargs):
        pytest.fail("cache_only request attempted a remote tile fetch")

    monkeypatch.setattr("urllib.request.urlopen", forbidden_network)
    with TestClient(create_admin_app()) as client:
        yield client


@pytest.mark.parametrize("exact", [False, True])
@pytest.mark.parametrize(
    ("stored_layer", "requested_layer"),
    [("rudy-twmap", "rudy-twmap"), ("imagery", "rudy-twmap"), ("rudy-twmap", "imagery")],
)
def test_cache_only_reads_exact_source_revision_across_rudy_namespaces(
    tmp_path, cache_client, stored_layer, requested_layer, exact
):
    source = imagery_source_for_project({}, source_id=SOURCE_ID)
    source_path = imagery_source_raster_tile_cache_path(
        PROJECT, stored_layer, source, *TILE, cache_root=tmp_path
    )
    expected = _write(source_path)

    response = cache_client.get(
        _url(requested_layer, query=f"cache_only=1&exact={int(exact)}")
    )

    assert response.status_code == 200
    assert response.content == expected
    assert response.headers["x-scout-tile-source"] == "local_source_cache"
    assert response.headers["x-scout-imagery-source-id"] == SOURCE_ID
    if exact:
        assert response.headers["x-scout-tile-exact"] == "true"
        assert response.headers["x-scout-tile-zoom"] == "16"
    # Reading the compatibility namespace must not duplicate or rewrite tiles.
    assert list(tmp_path.rglob("*.png")) == [source_path]


@pytest.mark.parametrize("mismatch", ["source", "revision", "namespace", "project"])
def test_exact_cache_lookup_does_not_scan_other_sources_or_revisions(
    tmp_path, cache_client, mismatch
):
    source = imagery_source_for_project({}, source_id=SOURCE_ID)
    if mismatch == "source":
        source = imagery_source_for_project({}, source_id="happyman_rudy")
    elif mismatch == "revision":
        source = {**source, "url_template": "https://example.invalid/old/{z}/{x}/{y}.png"}
    source_path = imagery_source_raster_tile_cache_path(
        "other_project" if mismatch == "project" else PROJECT,
        "unrelated" if mismatch == "namespace" else "imagery",
        source,
        *TILE,
        cache_root=tmp_path,
    )
    _write(source_path)

    response = cache_client.get(_url())

    assert response.status_code == 404
    assert list(tmp_path.rglob("*.png")) == [source_path]


def test_exact_request_rejects_parent_while_legacy_request_can_upscale(
    tmp_path, cache_client
):
    z, x, y = TILE
    parent_path = raster_tile_cache_path(
        PROJECT, "rudy-twmap", z - 2, x // 4, y // 4, cache_root=tmp_path
    )
    _write(parent_path)

    exact = cache_client.get(_url())
    legacy = cache_client.get(_url(query="cache_only=1"))

    assert exact.status_code == 404
    assert legacy.status_code == 200
    assert legacy.headers["x-scout-tile-source"] == "local_parent_cache_fallback"
    assert list(tmp_path.rglob("*.png")) == [parent_path]


def test_exact_request_rejects_transparent_placeholder_but_legacy_remains_compatible(
    tmp_path, cache_client
):
    source = imagery_source_for_project({}, source_id=SOURCE_ID)
    source_path = imagery_source_raster_tile_cache_path(
        PROJECT, "imagery", source, *TILE, cache_root=tmp_path
    )
    _write(source_path, TRANSPARENT_PNG_TILE)

    exact = cache_client.get(_url())
    legacy_missing = cache_client.get(
        _url(query="cache_only=1").replace(f"/{TILE[2]}.png", f"/{TILE[2] + 1}.png")
    )

    assert exact.status_code == 404
    assert legacy_missing.status_code == 200
    assert legacy_missing.headers["x-scout-tile-source"] == "transparent_fallback"
    assert legacy_missing.content == TRANSPARENT_PNG_TILE


def test_exact_rudy_request_can_read_its_prepared_layer_cache(tmp_path, cache_client):
    prepared = raster_tile_cache_path(PROJECT, "rudy-twmap", *TILE, cache_root=tmp_path)
    expected = _write(prepared)

    response = cache_client.get(_url())

    assert response.status_code == 200
    assert response.content == expected
    assert response.headers["x-scout-tile-source"] == "local_cache"


def test_exact_rudy_request_never_treats_bare_imagery_as_rudy(tmp_path, cache_client):
    aerial = raster_tile_cache_path(PROJECT, "imagery", *TILE, cache_root=tmp_path)
    _write(aerial)

    assert cache_client.get(_url("imagery")).status_code == 404
    assert cache_client.get(_url()).status_code == 404


@pytest.mark.parametrize(
    "query",
    ["cache_only=1&native=1&exact=1", "cache_only=1&refresh=1&exact=1"],
)
def test_exact_query_does_not_relax_remote_fetch_authorization(cache_client, query):
    assert cache_client.get(_url(query=query)).status_code == 422


def test_exact_native_remote_failure_does_not_upscale_or_return_placeholder(tmp_path):
    source = imagery_source_for_project({}, source_id=SOURCE_ID)
    calls = []

    def missing_tile(*_args, **_kwargs):
        calls.append(True)
        raise TimeoutError("tile unavailable")

    with pytest.raises(FileNotFoundError, match="unavailable"):
        load_or_build_raster_tile_payload(
            PROJECT, "rudy-twmap", *TILE, cache_root=tmp_path,
            imagery_source=source, require_exact_zoom=True,
            allow_remote_fetch=True, prefer_native_zoom=True,
            remote_fetcher=missing_tile,
        )
    assert calls == [True]
    assert not list(tmp_path.rglob("*.png"))
