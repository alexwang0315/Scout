import json
from pathlib import Path

from pretrip_offline_map_handoff import build_offline_map_handoff
from tests.test_admin_local_raster_source import _write_sample_geotiff


def test_builds_mac_to_scout_offline_map_handoff_package(tmp_path: Path) -> None:
    source = tmp_path / "source.tiff"
    kmz = tmp_path / "source.kmz"
    package = tmp_path / "handoff"
    _write_sample_geotiff(source)
    kmz.write_bytes(b"fixture-kmz")

    handoff = build_offline_map_handoff(
        project_id="chilai_nanhua_day1",
        source_geotiff=source,
        source_kmz=kmz,
        package_root=package,
        scout_data_root="/data/scout",
        min_zoom=5,
        max_zoom=5,
        max_tiles=1,
    )

    assert handoff["artifact_kind"] == "pretrip_offline_map_handoff_package"
    assert handoff["source_role"] == "user_provided_imagery"
    assert handoff["boundary"]["mac_build_required"] is True
    assert handoff["boundary"]["scout_runtime_tile_cutting_required"] is False
    assert handoff["boundary"]["external_network_required"] is False
    assert handoff["workspace_project_refs"]["imagery_manifest_ref"] == (
        "outputs/layers/manifests/"
        "chilai_nanhua_day1.local_raster_source_manifest.json"
    )
    assert handoff["workspace_project_refs"]["imagery_source_tiff_ref"] == (
        "/data/scout/raster-sources/chilai_nanhua_day1/source.tiff"
    )
    assert Path(handoff["source_files"]["geotiff"]).exists()
    assert Path(handoff["source_files"]["kmz"]).exists()
    assert any((package / "raster-tiles").glob("**/*.png"))

    source_manifest = json.loads(
        (
            package
            / "admin/pretrip-workspaces/chilai_nanhua_day1/outputs/layers/"
            / "manifests/chilai_nanhua_day1.local_raster_source_manifest.json"
        ).read_text(encoding="utf-8")
    )
    tile_plan = json.loads(
        (
            package
            / "admin/pretrip-workspaces/chilai_nanhua_day1/outputs/layers/"
            / "manifests/chilai_nanhua_day1.raster_tile_pyramid_plan.json"
        ).read_text(encoding="utf-8")
    )
    package_manifest = json.loads(
        (package / "offline_map_handoff_manifest.json").read_text(encoding="utf-8")
    )

    assert source_manifest["source_file"]["path"] == (
        "/data/scout/raster-sources/chilai_nanhua_day1/source.tiff"
    )
    assert source_manifest["source_file"]["storage_scope"] == "mac_to_scout_handoff"
    assert source_manifest["handoff"]["transport"] == "mac_build_to_scout_rsync"
    assert tile_plan["cache_root"] == "/data/scout/raster-tiles"
    assert tile_plan["source_geotiff_path"] == (
        "/data/scout/raster-sources/chilai_nanhua_day1/source.tiff"
    )
    assert package_manifest["rsync_hint"].startswith("rsync -a ")
