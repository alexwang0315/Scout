from pathlib import Path

import pytest

from admin_local_raster_source import (
    build_local_raster_source_manifest,
    write_local_raster_source_manifest,
)


def test_builds_local_geotiff_manifest_from_wgs84_tags(tmp_path):
    source = tmp_path / "sample_wgs84.tiff"
    _write_sample_geotiff(source)

    manifest = build_local_raster_source_manifest(
        source,
        project_id="chilai_nanhua_day1",
    )

    assert manifest["artifact_kind"] == "admin_local_raster_source_manifest"
    assert manifest["project_id"] == "chilai_nanhua_day1"
    assert manifest["layer_id"] == "imagery"
    assert manifest["source_kind"] == "local_geotiff"
    assert manifest["source_file"]["path"] == str(source)
    assert manifest["source_file"]["storage_scope"] == "local_cache_only"
    assert manifest["source_file"]["repo_fixture_write_allowed"] is False
    assert manifest["source_file"]["raw_raster_committed_to_repo_allowed"] is False
    assert manifest["source_file"]["sha256"]
    assert manifest["image"]["width_px"] == 4
    assert manifest["image"]["height_px"] == 3
    assert manifest["georeference"]["status"] == "geotiff_wgs84"
    assert manifest["georeference"]["crs"]["code"] == 4326
    assert manifest["georeference"]["crs"]["name"] == "WGS 84"
    assert manifest["georeference"]["bbox_wgs84"] == {
        "south": pytest.approx(23.94),
        "west": pytest.approx(121.0),
        "north": pytest.approx(24.0),
        "east": pytest.approx(121.04),
    }
    assert manifest["external_network_required"] is False
    assert manifest["tile_cutting_performed"] is False
    assert manifest["derived_tiles_written"] is False


def test_warns_when_geotiff_is_placed_inside_manifest_directory(tmp_path):
    manifest_dir = tmp_path / "manifests"
    manifest_dir.mkdir()
    source = manifest_dir / "sample_wgs84.tiff"
    _write_sample_geotiff(source)

    manifest = build_local_raster_source_manifest(source)

    assert manifest["placement"]["in_manifest_directory"] is True
    assert "manifests/" in manifest["placement"]["warning"]


def test_writes_small_json_descriptor_without_copying_raster(tmp_path):
    source = tmp_path / "sample_wgs84.tiff"
    output = tmp_path / "manifest.json"
    _write_sample_geotiff(source)
    manifest = build_local_raster_source_manifest(source)

    written = write_local_raster_source_manifest(manifest, output)

    assert written == output
    assert output.exists()
    assert output.stat().st_size < 8 * 1024
    assert source.exists()


def _write_sample_geotiff(path: Path) -> None:
    try:
        from PIL import Image, TiffImagePlugin
    except Exception as exc:  # pragma: no cover - environment guard
        pytest.skip(f"Pillow is unavailable: {exc}")

    image = Image.new("RGB", (4, 3), color=(16, 32, 48))
    tags = TiffImagePlugin.ImageFileDirectory_v2()
    tags[33550] = (0.01, 0.02, 0.0)
    tags[33922] = (0.0, 0.0, 0.0, 121.0, 24.0, 0.0)
    tags[34735] = (
        1,
        1,
        0,
        4,
        1024,
        0,
        1,
        2,
        1025,
        0,
        1,
        1,
        2048,
        0,
        1,
        4326,
        2049,
        34737,
        7,
        0,
    )
    tags[34737] = "WGS 84|"
    image.save(path, format="TIFF", tiffinfo=tags)
