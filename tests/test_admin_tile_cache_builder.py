import json
import subprocess
import sys
from pathlib import Path

import pytest

from admin_tile_cache_builder import (
    DEFAULT_TILE_CACHE_CAPACITY_BYTES,
    build_tile_cache_hardware_manifest,
    build_tile_cache_plan,
    expand_bbox_wgs84,
    is_public_osm_tile_template,
    load_pretrip_project_route_bbox,
    seed_tile_cache,
    write_tile_cache_manifest,
)


ROOT = Path(__file__).resolve().parents[1]
CHILAI_PROJECT_ROOT = (
    ROOT / "tests" / "fixtures" / "pretrip" / "projects" / "chilai_nanhua_day1"
)


def test_expands_bbox_by_fifty_percent_total_width_and_height():
    expanded = expand_bbox_wgs84(
        {"south": 24.0, "west": 121.0, "north": 24.2, "east": 121.4},
        expansion_ratio=0.5,
    )

    assert expanded == {
        "south": 23.95,
        "west": 120.9,
        "north": 24.25,
        "east": 121.5,
    }


def test_builds_chilai_tile_cache_plan_for_hardware_capacity_limit():
    bbox = load_pretrip_project_route_bbox(CHILAI_PROJECT_ROOT)
    plan = build_tile_cache_plan(bbox)

    assert plan["artifact_kind"] == "admin_tile_cache_plan"
    assert plan["status"] == "planned_capacity_ok"
    assert plan["cache_root"] == str(Path("~/.cache/scout-fusion/osm-tiles").expanduser())
    assert plan["hardware_deploy_target"] == "scout_hardware"
    assert plan["bbox_expansion_ratio"] == 0.5
    assert plan["min_zoom"] == 5
    assert plan["max_zoom"] == 20
    assert plan["capacity_limit_bytes"] == DEFAULT_TILE_CACHE_CAPACITY_BYTES
    assert plan["within_capacity_limit"] is True
    assert plan["total_tile_count"] > 0
    assert plan["estimated_total_bytes"] < DEFAULT_TILE_CACHE_CAPACITY_BYTES
    assert plan["zoom_ranges"][0]["z"] == 5
    assert plan["zoom_ranges"][-1]["z"] == 20
    assert plan["zoom_ranges"][-1]["tile_count"] > plan["zoom_ranges"][-2]["tile_count"]
    assert plan["downloads_tiles_into_repo"] is False
    assert plan["repo_fixture_write_allowed"] is False
    assert plan["source_policy_status"] == "public_osm_bulk_download_prohibited"
    assert plan["bulk_download_allowed"] is False


def test_hardware_manifest_keeps_cache_outside_repo_and_names_runtime_proxy():
    plan = build_tile_cache_plan(
        {"south": 24.0, "west": 121.0, "north": 24.01, "east": 121.01},
        tile_url_template="https://tiles.permitted.example/{z}/{x}/{y}.png",
    )
    manifest = build_tile_cache_hardware_manifest(plan)

    assert manifest["artifact_kind"] == "admin_tile_cache_hardware_manifest"
    assert manifest["status"] == "ready_for_permitted_tile_source"
    assert manifest["hardware_deploy_target"] == "scout_hardware"
    assert manifest["runtime_tile_url_template"] == "/admin/tiles/osm/{z}/{x}/{y}.png"
    assert manifest["repo_fixture_write_allowed"] is False
    assert "rsync -a --delete" in manifest["rsync_hint"]


def test_seed_blocks_public_osm_bulk_download_and_requires_provider_ack(tmp_path):
    public_plan = build_tile_cache_plan(
        {"south": 24.0, "west": 121.0, "north": 24.01, "east": 121.01},
        cache_root=tmp_path,
    )
    assert is_public_osm_tile_template(public_plan["tile_url_template"]) is True

    with pytest.raises(ValueError, match="bulk/offline prefetch is prohibited"):
        seed_tile_cache(public_plan, provider_allows_offline_prefetch=True)

    permitted_plan = build_tile_cache_plan(
        {"south": 24.0, "west": 121.0, "north": 24.001, "east": 121.001},
        cache_root=tmp_path,
        min_zoom=5,
        max_zoom=5,
        tile_url_template="https://tiles.permitted.example/{z}/{x}/{y}.png",
    )
    with pytest.raises(ValueError, match="provider_allows_offline_prefetch"):
        seed_tile_cache(permitted_plan)


def test_seed_writes_permitted_provider_tiles_with_fake_transport(tmp_path):
    plan = build_tile_cache_plan(
        {"south": 24.0, "west": 121.0, "north": 24.001, "east": 121.001},
        cache_root=tmp_path,
        min_zoom=5,
        max_zoom=5,
        tile_url_template="https://tiles.permitted.example/{z}/{x}/{y}.png",
    )
    seen = []

    def fake_fetch(url, headers):
        seen.append((url, headers))
        return b"\x89PNG\r\n\x1a\nfake-tile"

    summary = seed_tile_cache(
        plan,
        provider_allows_offline_prefetch=True,
        dry_run=False,
        fetch_tile=fake_fetch,
    )

    assert summary["status"] == "seed_complete"
    assert summary["tiles_written"] == plan["total_tile_count"]
    assert summary["bytes_written"] > 0
    assert seen
    assert seen[0][1]["User-Agent"].startswith("ScoutFusionTileCache/")
    assert any(path.suffix == ".png" for path in tmp_path.rglob("*.png"))


def test_cli_writes_plan_and_hardware_manifest(tmp_path):
    output_path = tmp_path / "tile_cache_manifest.json"
    result = subprocess.run(
        [
            sys.executable,
            "admin_tile_cache_builder.py",
            "--project-root",
            str(CHILAI_PROJECT_ROOT),
            "--cache-root",
            str(tmp_path / "cache"),
            "--write-manifest",
            str(output_path),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    )

    payload = json.loads(output_path.read_text(encoding="utf-8"))
    stdout_payload = json.loads(result.stdout)

    assert payload == stdout_payload
    assert payload["plan"]["min_zoom"] == 5
    assert payload["plan"]["max_zoom"] == 20
    assert payload["plan"]["capacity_limit_gib"] == 10.0
    assert payload["hardware_manifest"]["cache_root"] == str(tmp_path / "cache")


def test_write_tile_cache_manifest_keeps_metadata_small(tmp_path):
    manifest_path = write_tile_cache_manifest(
        {"artifact_kind": "admin_tile_cache_manifest", "tiles": []},
        tmp_path / "manifest.json",
    )

    assert manifest_path.exists()
    assert manifest_path.stat().st_size < 1024
